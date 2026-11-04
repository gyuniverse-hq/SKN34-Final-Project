// glide_sim.mjs: stage 2 check. How the light direction the shader sees moves when the fitted direction changes.
//
// Runs the page's own code, cut out of components/ar/faceTrackerHtml.ts as text: glideLight() and the direction update
// inside sampleScene() (from `if (mag > 1e-6) {` to the renormalisation). The fit itself is replaced by a scripted
// direction, so this measures smoothing only, not the estimate.
//
// Old = lightDirGlide false: the shader gets light.dir, which moves only when sampleScene() runs (every lightEveryMs) by the
// EMA k = lightSmoothing. New = lightDirGlide true: snap past lightDirSnapDeg, then shownLight.dir glides every frame.
//
//   node research/light_eval/glide_sim.mjs [--fps 30] [--out research/light_eval/results/stage2_glide.json]
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PAGE = resolve(HERE, '../../components/ar/faceTrackerHtml.ts');
const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };
const FPS = Number(opt('--fps', '30'));
const OUT = resolve(opt('--out', resolve(HERE, 'results/stage2_glide.json')));

const src = readFileSync(PAGE, 'utf8').replace(/\r\n/g, '\n');
const cut = (from, to) => {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error(`not found in page: ${from}`);
  return src.slice(a, b + to.length);
};
const num = (name) => Number(src.match(new RegExp(`\\b${name}: ([0-9.]+)`))[1]);
const glideSrc = cut('  function glideLight(now) {', '    return shownLight;\n  }');
const dirSrc = cut('        if (mag > 1e-6) {', '          light.dir = light.dir.map((v) => v / dl);\n        }');

function makeSim(glideOn) {
  const TUNING = {
    lightDirGlide: glideOn, lightDirSec: num('lightDirSec'), lightDirSnapDeg: num('lightDirSnapDeg'),
    lightDisplaySec: num('lightDisplaySec'), skinRefLum: num('skinRefLum'), exposureRange: [0.2, 1.6],
  };
  return new Function('TUNING', 'start', `
    const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
    const light = { color: [1, 1, 1], colorConf: 0, dir: start.slice(), strength: 1, dirConf: 1, skinMeanLum: TUNING.skinRefLum };
    const shownLight = { color: [1, 1, 1], exposure: 1, skinMeanLum: TUNING.skinRefLum, dir: start.slice(), strength: 1, conf: 1, t: 0 };
    ${glideSrc}
    function update(target, k) {
      let dx = target[0], dy = target[1], dz = target[2];
      const mag = Math.hypot(dx, dy, dz);
      ${dirSrc}
    }
    return { light, shownLight, glideLight, update };
  `)(TUNING, START);
}

const vec = (azDeg, elDeg = 0) => {
  const az = (azDeg * Math.PI) / 180, el = (elDeg * Math.PI) / 180;
  return [Math.sin(az) * Math.cos(el), Math.sin(el), Math.cos(az) * Math.cos(el)];
};
const angle = (a, b) => (Math.acos(Math.min(1, Math.max(-1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))) * 180) / Math.PI;
const START = vec(0);
const EVERY = num('lightEveryMs');
const K = num('lightSmoothing');

// target(tMs) = direction the fit returns at that sample time.
function run(glideOn, target, seconds) {
  const s = makeSim(glideOn);
  const dtMs = 1000 / FPS;
  const trace = [];
  // The page's clock never reads 0 while a face is tracked (shownLight.t = 0 means "face just found: jump").
  const T0 = 1000;
  let lastLightAt = -Infinity;
  s.glideLight(T0 - dtMs);
  trace.push({ t: -dtMs, dir: START.slice() });
  for (let t = 0; t <= seconds * 1000 + 1e-6; t += dtMs) {
    if (t - lastLightAt >= EVERY - 1e-6) { lastLightAt = t; s.update(target(t), K); }
    const shown = s.glideLight(T0 + t);
    trace.push({ t, dir: (glideOn ? shown.dir : s.light.dir).slice() });
  }
  return trace;
}

function stepMetrics(trace, from, to) {
  const total = angle(from, to);
  let maxStep = 0, t90 = null;
  for (let i = 1; i < trace.length; i++) maxStep = Math.max(maxStep, angle(trace[i - 1].dir, trace[i].dir));
  for (let i = 0; i < trace.length; i++) {
    const rest = trace.slice(i).every((p) => angle(p.dir, to) <= 0.1 * total);
    if (rest) { t90 = trace[i].t / 1000; break; }
  }
  return { totalDeg: total, maxFrameStepDeg: maxStep, t90Sec: t90 };
}

const out = { page: PAGE, fps: FPS, lightEveryMs: EVERY, lightSmoothing: K, lightDirSec: num('lightDirSec'), lightDirSnapDeg: num('lightDirSnapDeg'), cases: {} };
for (const deg of [30, 15]) {
  const to = vec(deg);
  const target = () => to;
  out.cases[`step_${deg}deg`] = {
    note: `the fit turns ${deg}° once at t = 0 and stays`,
    old: stepMetrics(run(false, target, 6), START, to),
    new: stepMetrics(run(true, target, 6), START, to),
  };
}
// The fit turns 30° every 0.5 s (azimuth 0, 30, 0, 30, ...): only the largest frame-to-frame change is meaningful.
const flip = (t) => vec(Math.round(t / EVERY) % 2 ? 30 : 0);
const jitter = (glideOn) => {
  const tr = run(glideOn, flip, 6);
  let m = 0;
  for (let i = 1; i < tr.length; i++) m = Math.max(m, angle(tr[i - 1].dir, tr[i].dir));
  return { maxFrameStepDeg: m };
};
out.cases.flip_30deg_every_500ms = { note: 'the fit alternates between two directions 30° apart every 0.5 s', old: jitter(false), new: jitter(true) };

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify(out, null, 1));
const f = (v) => (v === null ? 'never' : v.toFixed(2));
for (const [name, c] of Object.entries(out.cases)) {
  console.log(name);
  for (const side of ['old', 'new']) {
    const m = c[side];
    console.log(`  ${side}: max frame step ${f(m.maxFrameStepDeg)}°` + (m.t90Sec !== undefined ? `, 90% at ${f(m.t90Sec)} s` : ''));
  }
}
console.log('->', OUT);
