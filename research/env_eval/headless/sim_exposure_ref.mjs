// Step 5-d (11-19) check: the page's own reference code (expRef collection in envEvaluate, exposureFor, pearlExposure, envReset)
// driven in time order by per-photo measures of the test split (normal / dark / dark_ae), at the phone's 0.5 s evaluation step.
// Usage: node sim_exposure_ref.mjs <built page.html> <run dir (manifest, lapa_env, skin_env csv)> <out.json>
// float = (makeup exposure / skin brightness) over the same ratio in this photo's normal light: 1 = the makeup sits on the
// skin as it does in normal light; > 1 = the makeup floats brighter than the skin. old = today's skin / 0.34 with the 0.2 floor.
import fs from 'fs';
const [, , pageFile, runDir, outFile] = process.argv;
const page = fs.readFileSync(pageFile, 'utf8');
function block(startKey) {
  const a = page.indexOf(startKey); if (a < 0) throw new Error('missing ' + startKey);
  let i = page.indexOf('{', a), d = 0;
  for (; i < page.length; i++) {
    const c = page[i];
    if (c === '/' && page[i + 1] === '/') { i = page.indexOf('\n', i); continue; }
    if (c === "'" || c === '"') { const q = c; i++; while (page[i] !== q) { if (page[i] === '\\') i++; i++; } continue; }
    if (c === '{') d++; else if (c === '}' && --d === 0) return page.slice(a, i + 1);
  }
  throw new Error('unclosed ' + startKey);
}
const tuningSrc = block('const TUNING = {');
const resetSrc = block('function envReset()');
const envSrc = page.slice(page.indexOf('const ENV_GROUPS'), page.indexOf(resetSrc) + resetSrc.length);

function makeWorld() {
  const N = 478, sx = new Float32Array(N).fill(0.5), sy = new Float32Array(N).fill(0.5), sz = new Float32Array(N);
  sx[234] = 0.3; sx[454] = 0.7; sy[10] = 0.3; sy[152] = 0.7;
  [[33, 0.38], [133, 0.45], [362, 0.55], [263, 0.62]].forEach(([i, x]) => { sx[i] = x; sy[i] = 0.45; });
  const light = { color: [1, 1, 1], colorConf: 0.9, colorSamples: 0, samples: 0, rawRb: 1, rawGm: 1, bgFraction: 0.5, grain: 0.02, skinMeanLum: 0.3, blownFrac: 0, snapColor: false };
  const clock = { t: 0 };
  const ctx = { performance: { now: () => clock.t }, sx, sy, sz, light, shownLight: { t: 1 }, faceSpeed: 0, post: () => {}, clamp: (v, a, b) => Math.min(b, Math.max(a, v)) };
  const f = new Function(...Object.keys(ctx), tuningSrc + ';\n' + envSrc + ';\nreturn { TUNING, envEvaluate, envReset, exposureFor, pearlExposure, envM, envState, expRef, envPrimary };');
  return { light, clock, api: f(...Object.values(ctx)) };
}
const csv = (p) => { const [h, ...r] = fs.readFileSync(p, 'utf8').trim().split(/\r?\n/); const k = h.split(','); return r.map((l) => Object.fromEntries(l.split(',').map((v, i) => [k[i], v]))); };
const man = csv(runDir + '/manifest.csv').filter((r) => r.split === 'test');
const rows = [...csv(runDir + '/lapa_env.csv'), ...csv(runDir + '/skin_env.csv')];
const meas = new Map(rows.map((r) => [r.img + '|' + r.cond, r]));
const group = (m) => (m.dataset === 'lapa' ? 'lapa' : m.tone);
const S = (r) => ({ skin: +r.skin_l, bg: +r.bg_l, frame: +r.frame_l, lr: +r.lr, grain: +r.grain, bgFrac: +r.bg_frac, blown: +r.blown });
const mix = (a, b, w) => Object.fromEntries(Object.keys(a).map((k) => [k, a[k] + w * (b[k] - a[k])]));

// one run: sceneAt(t) -> measure or null (face lost); returns exposure samples at the marks
function run(sceneAt, endMs, marks) {
  const { light, clock, api } = makeWorld();
  const base = (v) => Math.min(1.6, Math.max(0.2, v / 0.34));
  const out = {};
  let lost = false;
  for (let t = 0; t <= endMs; t += 500) {
    clock.t = t;
    const s = sceneAt(t);
    if (!s) { if (!lost) { lost = true; api.envReset(); light.samples = 0; light.colorSamples = 0; } continue; }
    lost = false;
    api.envM.faceLum = s.skin; api.envM.bgLum = s.bg; api.envM.frameLum = s.frame; api.envM.lr = s.lr;
    light.skinMeanLum += (light.samples++ ? 0.35 : 1) * (s.skin - light.skinMeanLum);
    light.grain = s.grain * 0.64; light.blownFrac = s.blown; light.bgFraction = s.bgFrac;
    api.envEvaluate(t, 720, 960);
    if (marks.includes(t)) {
      const e = api.exposureFor(light.skinMeanLum), eo = base(light.skinMeanLum);
      out[t] = { new: e / light.skinMeanLum, old: eo / light.skinMeanLum, dark: !!api.envState.on.dark, ref: api.expRef.n ? api.expRef.skin : 0, pearl: api.pearlExposure(light.skinMeanLum) };
    }
  }
  return out;
}
const q = (a, p) => { const b = [...a].sort((x, y) => x - y); return b[Math.min(b.length - 1, Math.round(p * (b.length - 1)))]; };
const res = {};
for (const m of man) {
  const nm = meas.get(m.img + '|normal'), dm = meas.get(m.img + '|dark'), am = meas.get(m.img + '|dark_ae');
  if (!nm || !dm || !am) continue;
  const N = S(nm), D = S(dm), A = S(am);
  const norm = (0.34 > 0 ? Math.min(1.6, Math.max(0.2, N.skin / 0.34)) / N.skin : 1);   // exposure / skin in this photo's normal light
  const sc = {
    // normal 0-20 s, then the light drops (dark room, no auto exposure)
    'A normal->dark': { f: (t) => (t < 20000 ? N : D), end: 40000, marks: [19500, 24000, 39500] },
    // starts in the dark (no reference possible), 20 s later the light is normal again
    'B dark->normal': { f: (t) => (t < 20000 ? D : N), end: 40000, marks: [19500, 24000, 39500] },
    // normal, then dark but the camera brightens the picture back (auto exposure): picture about the same, more noise
    'C normal->dark_ae': { f: (t) => (t < 20000 ? N : A), end: 40000, marks: [24000, 39500] },
    // normal, then the light fades to 0.2x over 30 s (a dimmer that may never reach the dark flag early)
    'D normal->fade': { f: (t) => (t < 20000 ? N : mix(N, D, Math.min(1, (t - 20000) / 30000))), end: 70000, marks: [35000, 49500, 69500] },
    // normal, the face is lost for 1 s (reference reset), then dark
    'E normal->lost->dark': { f: (t) => (t < 20000 ? N : t < 21000 ? null : D), end: 40000, marks: [24000, 39500] },
  };
  for (const [name, s] of Object.entries(sc)) {
    const r = run(s.f, s.end, s.marks);
    for (const t of s.marks) {
      const k = name + ' @' + t / 1000 + 's|' + group(m);
      const o = (res[k] ||= { n: 0, fNew: [], fOld: [], darkFlag: 0, noRef: 0, pearl: [] });
      o.n++; o.fNew.push(r[t].new / norm); o.fOld.push(r[t].old / norm); o.darkFlag += r[t].dark ? 1 : 0; o.noRef += r[t].ref ? 0 : 1; o.pearl.push(r[t].pearl);
    }
  }
}
const out = {};
for (const [k, o] of Object.entries(res)) {
  out[k] = { n: o.n, floatNew: [q(o.fNew, .5), q(o.fNew, .9)].map((x) => +x.toFixed(2)), floatOld: [q(o.fOld, .5), q(o.fOld, .9)].map((x) => +x.toFixed(2)), darkFlagPct: +(100 * o.darkFlag / o.n).toFixed(0), noRefPct: +(100 * o.noRef / o.n).toFixed(0), pearlMed: +q(o.pearl, .5).toFixed(2) };
}
fs.writeFileSync(outFile, JSON.stringify(out, null, 1));
console.log('scenario @time | tone n | float new p50/p90 | float old p50/p90 | dark flag % | no reference % | pearl');
for (const [k, v] of Object.entries(out)) console.log(k.padEnd(34), String(v.n).padStart(3), JSON.stringify(v.floatNew).padEnd(12), JSON.stringify(v.floatOld).padEnd(12), v.darkFlagPct + '%', v.noRefPct + '%', v.pearlMed);
