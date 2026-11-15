import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';

const html = FACE_TRACKER_HTML;

describe('matte specular mask and softer outer edge (11-13)', () => {
  it('keeps the matte mask values in range and registers/sets its uniform', () => {
    const m = html.match(/matteSpecMask: \[([\d.]+), ([\d.]+), ([\d.]+)\]/);
    expect(m).not.toBeNull();
    const [strength, ridge, scale] = [Number(m![1]), Number(m![2]), Number(m![3])];
    expect(strength).toBeGreaterThanOrEqual(0);
    expect(strength).toBeLessThanOrEqual(0.15);
    expect(ridge).toBeGreaterThanOrEqual(0);
    expect(ridge).toBeLessThanOrEqual(1);
    expect(scale).toBeGreaterThanOrEqual(0.05);
    expect(scale).toBeLessThanOrEqual(0.2);
    expect(html).toContain("'uMatteSpec'");
    expect(html).toMatch(/gl\.uniform3f\(u\.uMatteSpec,/);
  });

  it('builds the mask from local luminance contrast and only for matte roughness', () => {
    expect(html).toContain("'    float matteW = uMatteSpec.x > 0.0 ? smoothstep(0.8, 0.9, uLipRough) * core * (1.0 - skinRefW) : 0.0;',");
    expect(html).toContain("'    float crease = clamp((wideL - camL) / (uMatteSpec.z * meanL), -1.0, 1.0);',");
    expect(html).toContain('1.0 - smoothstep(0.0, 1.0, crease) + uMatteSpec.y * smoothstep(0.0, 1.0, -crease)');
    // The mask multiplies every reflection term: form shine, sheen, glint and the kept camera highlight.
    expect(html).toContain("'    formSpec *= specMask; sheen *= specMask;',");
    expect(html).toContain('vec3(hl * keepHl * specMask)');
  });

  it('softens the outer edge with a 16-tap kernel and keeps the fixed values that do not move it', () => {
    expect(html).toContain("'  vec2 sd = so * 0.7071;',");
    expect(html).toContain("'  return edgeRemap(a / w);',");
    expect(html).toContain('lipEdgeBlurK: 1.5,');
    expect(html).toContain('lipEdgeSoftMax: 3.0,');
    // Unchanged on purpose: these do not move the on-screen edge (measured 11-13).
    expect(html).toContain('lipEdgePx: 2,');
    expect(html).toContain('lipFeatherPx: 3,');
  });
});

describe('lip edge that scales with the lip (11-13)', () => {
  it('has the proportional radius, the inward remap and the two-ring kernel, each switched off by zero', () => {
    const fk = html.match(/lipEdgeFeatherK: ([\d.]+)/);
    const sk = html.match(/lipEdgeSoftMaxK: ([\d.]+)/);
    const inset = html.match(/lipEdgeInset: \[([\d.]+), ([\d.]+), ([\d.]+)\]/);
    expect(fk && sk && inset).toBeTruthy();
    expect(Number(fk![1])).toBeLessThanOrEqual(0.5);
    expect(Number(sk![1])).toBeLessThanOrEqual(1);
    expect(Number(inset![1])).toBeLessThan(Number(inset![2]));
    expect(Number(inset![3])).toBeLessThanOrEqual(1);
    expect(html).toContain("'uLipFeather'");
    expect(html).toMatch(/gl\.uniform3f\(u\.uLipFeather,/);
    expect(html).toContain("'    float soft = edgeSoft(suv, so);',");
    // The overlip test (skinRefW) uses the same kernel and remap as the paint edge, or the two disagree.
    expect(html).toContain("'    float insideBase = edgeSoftBase(suv, so);',");
    expect(html).toContain("'float edgeSoftBase(vec2 s, vec2 so) { return edgeKernel(s, so, true); }',");
    expect(html).toContain('float edgeRemap(float a) { return uLipFeather.x > 0.0 ? smoothstep(uLipFeather.x, uLipFeather.y, a) : a; }');
  });
});

describe('steady lip outline (11-15)', () => {
  it('smooths the camera-colour pull/push per vertex and the edge radius thickness', () => {
    const num = (k: string) => Number(html.match(new RegExp(`${k}: ([0-9.]+)`))![1]);
    expect(num('lipEdgePullSmooth')).toBeGreaterThan(0);
    expect(num('lipEdgePullSmooth')).toBeLessThanOrEqual(1);
    expect(num('lipEdgeStepMax')).toBeGreaterThan(0);
    expect(num('lipEdgeStepMax')).toBeLessThanOrEqual(0.15);
    expect(num('lipThickSmooth')).toBeGreaterThan(0);
    expect(html).toContain('lipPullSm[j] += clamp(k * (target - lipPullSm[j]), -cap, cap);');
    expect(html).toContain('lipThickSm = lipThickSm > 0 ? lipThickSm + TUNING.lipThickSmooth * (lipThickNow - lipThickSm) : lipThickNow;');
  });
});
