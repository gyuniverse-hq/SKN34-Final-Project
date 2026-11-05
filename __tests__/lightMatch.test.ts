import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';

type Vec3 = [number, number, number];
type Grid = object;
type Estimators = {
  fitLight: (samples: number[][]) => number[] | null;
  faceHeightGrid: (pos: Float32Array, tris: number[], res: number) => Grid;
  matchLight: (grid: Grid, pos: Float32Array, nrm: Float32Array, verts: number[], lums: number[], spread: number, maxVerts: number) =>
    { dir: Vec3; r2: number; peak: number } | null;
};

function estimators(): Estimators {
  const match = FACE_TRACKER_HTML.match(/<script type="module">([\s\S]*?)<\/script>/);
  if (!match) throw new Error('module script not found');
  const script = match[1];
  const source = script.slice(script.indexOf('  function solve4('), script.indexOf('  function ensureFoundSkinBuffers('));
  return new Function(`${source}; return { fitLight, faceHeightGrid, matchLight };`)() as Estimators;
}

// Synthetic face in the page's shading frame (x right, y up, z toward the viewer, pixels):
// an ellipsoid with a nose ridge and a brow ridge, so side light throws real cast shadows.
function height(x: number, y: number) {
  const e = 1 - (x * x) / (110 * 110) - (y * y) / (140 * 140);
  if (e <= 0) return 0;
  const nose = 28 * Math.exp(-(x * x) / (2 * 9 * 9) - ((y - 5) * (y - 5)) / (2 * 28 * 28));
  const brow = 10 * Math.exp(-((y - 45) * (y - 45)) / (2 * 8 * 8)) * Math.exp(-(x * x) / (2 * 50 * 50));
  return 70 * Math.sqrt(e) + nose + brow;
}

function dirFrom(azDeg: number, elDeg: number): Vec3 {
  const a = (azDeg * Math.PI) / 180, e = (elDeg * Math.PI) / 180;
  return [Math.sin(a) * Math.cos(e), Math.sin(e), Math.cos(a) * Math.cos(e)];
}

function litTruth(x: number, y: number, z: number, d: Vec3) {
  const r = Math.hypot(d[0], d[1]);
  if (r < 1e-6) return 1;
  for (let s = 1; s < 400; s += 0.5) {
    const qz = z + (d[2] / r) * s;
    if (qz > 120) return 1;
    if (height(x + (d[0] / r) * s, y + (d[1] / r) * s) > qz + 0.5) return 0;
  }
  return 1;
}

function scene(light: Vec3) {
  const step = 8, xs: number[] = [];
  for (let v = -104; v <= 104; v += step) xs.push(v);
  const n = xs.length;
  const pos = new Float32Array(n * n * 3), nrm = new Float32Array(n * n * 3);
  xs.forEach((y, j) => xs.forEach((x, i) => {
    const k = (j * n + i) * 3, h = 0.5;
    const gx = (height(x + h, y) - height(x - h, y)) / (2 * h), gy = (height(x, y + h) - height(x, y - h)) / (2 * h);
    const len = Math.hypot(gx, gy, 1);
    pos.set([x, y, height(x, y)], k);
    nrm.set([-gx / len, -gy / len, 1 / len], k);
  }));
  const tris: number[] = [];
  for (let j = 0; j < n - 1; j++) {
    for (let i = 0; i < n - 1; i++) {
      const a = j * n + i;
      tris.push(a, a + 1, a + n, a + 1, a + n + 1, a + n);
    }
  }
  let seed = 7;
  const noise = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648 - 0.5) * 0.02;
  const verts: number[] = [], lums: number[] = [];
  for (let v = 0; v < n * n; v++) {
    const k = v * 3;
    // Same skin filter as the page: on the face and facing the camera.
    if (pos[k + 2] < 15 || nrm[k + 2] < 0.35) continue;
    const ndl = nrm[k] * light[0] + nrm[k + 1] * light[1] + nrm[k + 2] * light[2];
    const lit = ndl > 0 ? ndl * litTruth(pos[k], pos[k + 1], pos[k + 2], light) : 0;
    verts.push(v);
    lums.push(0.05 + 0.6 * lit + noise());
  }
  return { pos, nrm, tris, verts, lums };
}

function angleDeg(a: number[], b: number[]) {
  const la = Math.hypot(a[0], a[1], a[2]), lb = Math.hypot(b[0], b[1], b[2]);
  return (Math.acos(Math.min(1, (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (la * lb))) * 180) / Math.PI;
}

// The page's straight-line estimate: fit, drop the worst 20%, refit, clamp z ≥ 0.
function oldEstimate(e: Estimators, s: ReturnType<typeof scene>) {
  const samples = s.verts.map((v, i) => [s.nrm[v * 3], s.nrm[v * 3 + 1], s.nrm[v * 3 + 2], s.lums[i]]);
  let fit = e.fitLight(samples)!;
  const resid = samples.map((p) => Math.abs(p[3] - (fit[0] + fit[1] * p[0] + fit[2] * p[1] + fit[3] * p[2])));
  const cut = resid.slice().sort((p, q) => p - q)[Math.floor(resid.length * 0.8)];
  fit = e.fitLight(samples.filter((_, i) => resid[i] <= cut)) || fit;
  return [fit[1], fit[2], Math.max(fit[3], 0)];
}

describe('light by matching candidate lights (TUNING.lightMatch)', () => {
  const e = estimators();
  const lights: [string, Vec3][] = [
    ['upper left side', dirFrom(-55, 30)],
    ['right, slightly low', dirFrom(50, -10)],
    ['overhead', dirFrom(10, 55)],
    ['near frontal', dirFrom(5, 8)],
  ];

  it.each(lights)('recovers %s light within 15° and no worse than the straight-line fit', (_, light) => {
    const s = scene(light);
    const match = e.matchLight(e.faceHeightGrid(s.pos, s.tris, 48), s.pos, s.nrm, s.verts, s.lums, 0.02, 160);
    expect(match).not.toBeNull();
    const errMatch = angleDeg(match!.dir, light);
    const errFit = angleDeg(oldEstimate(e, s), light);
    expect(errMatch).toBeLessThan(15);
    expect(errMatch).toBeLessThanOrEqual(errFit + 2);
    expect(match!.r2).toBeGreaterThan(0.9);
    expect(match!.peak).toBeGreaterThan(0.5);
  });

  // 11-04 user decision after the phone check (side light followed, front light unchanged, no lag): on by default.
  it('is on by default and replaces the straight-line direction when it finds a match', () => {
    expect(FACE_TRACKER_HTML).toContain('lightMatch: true,');
    expect(FACE_TRACKER_HTML).toContain('if (match) { [dx, dy, dz] = match.dir; mag = 1; r2 = match.r2; peak = match.peak; }');
  });
});
