// Step 3-a check (11-19). Usage: node sim_cam_settle.mjs <built page.html> <run dir with manifest / lapa_env / skin_env csv> <lib/arEnv.ts> <out.json>
// Step 3-a check: the page's own env code (envStep / envEvaluate / envCameraChanged, sliced from the built page) driven by
// per-image measures of LaPa + Roboflow skin-tone test-split photos (research/data/env_eval_runs/2026-11-19), phone timing.
import fs from 'fs';
import { pathToFileURL } from 'url';
const [, , pageFile, runDir, libPath, outFile] = process.argv;
const page = fs.readFileSync(pageFile, 'utf8');
function block(startKey) {   // from startKey to its matching close brace (skipping // comments and strings)
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
const lib = await import(pathToFileURL(libPath).href);

function makeWorld() {
  const N = 478, sx = new Float32Array(N).fill(0.5), sy = new Float32Array(N).fill(0.5), sz = new Float32Array(N);
  sx[234] = 0.3; sx[454] = 0.7; sy[10] = 0.3; sy[152] = 0.7;
  [[33, 0.38], [133, 0.45], [362, 0.55], [263, 0.62]].forEach(([i, x]) => { sx[i] = x; sy[i] = 0.45; });
  const light = { color: [1, 1, 1], colorConf: 0.9, colorSamples: 0, samples: 0, rawRb: 1, rawGm: 1, bgFraction: 0.5, grain: 0.02, skinMeanLum: 0.3, blownFrac: 0, snapColor: false };
  const shownLight = { t: 1 };
  const posted = [];
  const ctx = { sx, sy, sz, light, shownLight, faceSpeed: 0, post: (m) => posted.push(m), clamp: (v, a, b) => Math.min(b, Math.max(a, v)) };
  const f = new Function(...Object.keys(ctx), tuningSrc + ';\n' + envSrc + ';\nreturn { TUNING, envEvaluate, envCameraChanged, envM, envState, envRef, envPrimary, get camSnapPending() { return camSnapPending; }, set camSnapPending(v) { camSnapPending = v; } };');
  const api = f(...Object.values(ctx));
  return { ...ctx, api, posted };
}
const csv = (p) => { const [h, ...r] = fs.readFileSync(p, 'utf8').trim().split(/\r?\n/); const k = h.split(','); return r.map((l) => Object.fromEntries(l.split(',').map((v, i) => [k[i], v]))); };
const man = csv(runDir + '/manifest.csv').filter((r) => r.split === 'test');
const rows = [...csv(runDir + '/lapa_env.csv'), ...csv(runDir + '/skin_env.csv')];
const meas = new Map(rows.map((r) => [r.img + '|' + r.cond, r]));
const group = (m) => (m.dataset === 'lapa' ? 'lapa' : m.tone);
function scene(r) {
  const gw = [+r.gw_r, +r.gw_g, +r.gw_b], ge = [+r.ge_r, +r.ge_g, +r.ge_b];
  const est = gw.map((v, j) => v + 0.75 * (ge[j] - v));
  const lumOf = (a, b, c) => 0.2126 * a + 0.7152 * b + 0.0722 * c;
  const cl = est.map((v) => Math.min(2, Math.max(0.5, v)));
  const cy = lumOf(...cl);
  return { faceLum: +r.skin_l, bgLum: +r.bg_l, frameLum: +r.frame_l, lr: +r.lr, grain: +r.grain, bgFrac: +r.bg_frac, blown: +r.blown,
    rawRb: est[0] / Math.max(1e-4, est[2]), rawGm: est[1] / Math.max(1e-4, 0.5 * (est[0] + est[2])), color: cl.map((v) => v / cy) };
}
// One run: sceneAt(t) = the camera picture at t (ms); lockAt = when the white-balance lock succeeds; use3a = call
// envCameraChanged there (new code) or not (before). Phone timing: eval and scene sample every 500 ms; colour estimate on
// each segmentation, every 1000 ms auto / 2000 ms locked, right away on a snap (light.snapColor).
function run(sceneAt, lockAt, use3a, endMs) {
  const w = makeWorld(), { api, light } = w;
  let locked = false, lastSeg = -1e9, resnapped = false;
  const on = []; const err = [];
  let disp = lib.initialEnvDisplay(); const shown = [];
  for (let t = 0; t <= endMs; t += 500) {
    if (!locked && t >= lockAt) { locked = true; if (use3a) api.envCameraChanged(t); if (use3a === 'snapOnly') api.envState.camHoldUntil = 0; }
    // candidate 3-a+: one more snap when the hold ends (the first post-lock sample may be the camera still settling)
    if (use3a === 'resnap' && !resnapped && t >= lockAt + 1500) { resnapped = true; light.snapColor = true; }
    const s = sceneAt(t);
    api.envM.faceLum = s.faceLum; api.envM.bgLum = s.bgLum; api.envM.frameLum = s.frameLum; api.envM.lr = s.lr;
    light.skinMeanLum += (light.samples++ ? 0.35 : 1) * (s.faceLum - light.skinMeanLum);
    light.grain = s.grain; light.blownFrac = s.blown; light.bgFraction = s.bgFrac;
    // candidate 'fastResample': while the hold lasts (and 1 s after), the colour is re-read every 500 ms, not every 2 s
    const fast = use3a === 'fastResample' && t >= lockAt && t <= lockAt + 2500;
    if (light.snapColor || fast || t - lastSeg >= (locked ? 2000 : 1000)) {
      lastSeg = t;
      const snap = light.snapColor;
      const kc = light.colorSamples++ === 0 || snap ? 1 : locked ? 0.35 : 0.6;
      if (snap) light.snapColor = false;
      if (snap && api.camSnapPending) { api.camSnapPending = false; w.shownLight.t = 0; }
      light.rawRb = s.rawRb; light.rawGm = s.rawGm;
      for (let j = 0; j < 3; j++) light.color[j] += kc * (s.color[j] - light.color[j]);
    }
    api.envEvaluate(t, 720, 960);
    const items = Object.keys(api.envState.on).filter((k) => api.envState.on[k]);
    on.push([t, items]);
    if (t >= LOCK && t <= LOCK + 4000) err.push(Math.max(...[0, 1, 2].map((j) => Math.abs(light.color[j] - s.color[j]))));
    disp = lib.stepEnvDisplay(disp, { primary: api.envPrimary(), level: 'ok', items, ready: api.envState.evals >= 3 }, false, t);
    shown.push([t, disp.shown]);
  }
  return { on, shown, err: err.reduce((a, b) => a + b, 0) / Math.max(1, err.length) };
}
const LOCK = 6000, END = 15000;
const scen = {
  steady: (n) => () => n,                                               // the lock freezes the picture (its purpose)
  transient: (n, wm) => (t) => (t >= LOCK && t < LOCK + 1000 ? wm : n),  // camera jumps warm on the lock, back after 1 s
  transient2s: (n, wm) => (t) => (t >= LOCK && t < LOCK + 2000 ? wm : n),
  transient2_5s: (n, wm) => (t) => (t >= LOCK && t < LOCK + 2500 ? wm : n),
  persistent: (n, wm) => (t) => (t >= LOCK ? wm : n),                   // the lock leaves the camera at a warm default
  realWarm: (n, wm) => (t) => (t >= LOCK + 500 ? wm : n),               // a real warm lamp switched on 0.5 s after the lock
};
const res = {};
for (const m of man) {
  const n = meas.get(m.img + '|normal'), wm = meas.get(m.img + '|warm');
  if (!n || !wm) continue;
  const N = scene(n), WM = scene(wm);
  for (const [sn, mk] of Object.entries(scen)) for (const v of ['before', '3a', 'resnap', 'snapOnly', 'fastResample']) {
    const r = run(mk(N, WM), LOCK, v === 'before' ? false : v === '3a' ? true : v, END);
    const key = sn + '|' + v + '|' + group(m);
    const o = (res[key] ||= { n: 0, err: 0, msgWin: 0, condWin: 0, warmOnAt: [], msgs: {}, beforeLock: 0 });
    o.n++; o.err += r.err;
    const win = r.shown.filter(([t, s]) => t >= LOCK && t <= LOCK + 6000 && s && s !== 'normal');
    if (win.length) o.msgWin++;
    for (const s of new Set(win.map((x) => x[1]))) o.msgs[s] = (o.msgs[s] || 0) + 1;
    if (r.on.some(([t, it]) => t >= LOCK && t <= LOCK + 6000 && it.some((k) => ['warmLight', 'colorCast', 'lightChanged'].includes(k)))) o.condWin++;
    if (r.shown.some(([t, s]) => t < LOCK && s && s !== 'normal')) o.beforeLock++;
    const wOn = r.on.find(([t, it]) => t >= LOCK && it.includes('warmLight'));
    o.warmOnAt.push(wOn ? wOn[0] - LOCK : null);
  }
}
const out = {};
for (const [k, o] of Object.entries(res)) {
  const ws = o.warmOnAt.filter((x) => x != null).sort((a, b) => a - b);
  out[k] = { n: o.n, colourErr4s: +(o.err / o.n).toFixed(3), msgIn6sAfterLockPct: +(100 * o.msgWin / o.n).toFixed(1), colourCondIn6sPct: +(100 * o.condWin / o.n).toFixed(1),
    warmOnPct: +(100 * ws.length / o.n).toFixed(1), warmOnMedianMs: ws.length ? ws[ws.length >> 1] : null, msgBeforeLockPct: +(100 * o.beforeLock / o.n).toFixed(1), msgs: o.msgs };
}
fs.writeFileSync(outFile, JSON.stringify(out, null, 1));
for (const [k, v] of Object.entries(out)) console.log(k.padEnd(26), JSON.stringify(v));
