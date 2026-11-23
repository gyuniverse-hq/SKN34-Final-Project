// Lip shader setting trials on one still frame (8회차 멘토링 후속 5-c, 2026-11-23). No app source is changed.
// Builds the page from the current components/ar/faceTrackerHtml.ts, feeds a still face as a fake camera in headless Edge
// (SwiftShader), and for each trial: restores the default TUNING / MATERIALS, applies the trial's overrides, sends the lip
// through the app's window.__kb.receive path, waits, captures the canvas.
//   node research/makeup_gen/ar_tune_render.mjs <trials.json> <out_dir>
// trials.json: { "face": "<png>", "patches": [[find, replace]], "trials": [ { "name", "lip": {hex, texture, intensity}, "tuning": {...}, "materials": {"glossy": {...}} } ] }
// Light and segmenter are frozen after warm-up (as ar_render.mjs) so every trial sees the same light estimate.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';

const [, , trialsPath, outDir] = process.argv;
const ROOT = process.cwd();
const cfg = JSON.parse(fs.readFileSync(trialsPath, 'utf8'));
fs.mkdirSync(outDir, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const build = fs.mkdtempSync(path.join(os.tmpdir(), 'ar-tune-build-'));
const require = createRequire(import.meta.url);
const ts = require(path.join(ROOT, 'node_modules', 'typescript'));
for (const name of ['faceUV', 'faceTrackerHtml']) {
  const src = fs.readFileSync(path.join(ROOT, 'components', 'ar', name + '.ts'), 'utf8');
  fs.writeFileSync(path.join(build, name + '.js'), ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText);
}
let html = require(path.join(build, 'faceTrackerHtml.js')).FACE_TRACKER_HTML;
// cfg.patches: [[find, replace], ...] applied to the built page text (experimental shader terms for one study; each find must
// occur exactly once). The app source itself is never written.
for (const [a, b] of [['const TUNING = {', 'const TUNING = window.__TUNING = {'], ['const MATERIALS = {', 'const MATERIALS = window.__MAT = {'], ...(cfg.patches || [])]) {
  if (html.split(a).length !== 2) throw new Error('marker not found once: ' + a);
  html = html.replace(a, b);
}
const FAKE = `window.__msgs=[];window.ReactNativeWebView={postMessage:(s)=>window.__msgs.push(s)};
const __img=new Image();__img.src='/face.png';
navigator.mediaDevices.getUserMedia=async()=>{await __img.decode();const c=document.createElement('canvas');c.width=__img.naturalWidth;c.height=__img.naturalHeight;
const x=c.getContext('2d');const d=()=>{x.drawImage(__img,0,0);requestAnimationFrame(d)};d();return c.captureStream(30);};`;
const face = fs.readFileSync(path.resolve(cfg.face));
const server = http.createServer((q, r) => {
  if (q.url === '/face.png') { r.writeHead(200, { 'content-type': 'image/png' }); return r.end(face); }
  r.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }); r.end(html);
}).listen(0, '127.0.0.1');
await new Promise((r) => server.on('listening', r));
const url = 'http://127.0.0.1:' + server.address().port + '/';
const exe = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
const port = 9300 + Math.floor(Math.random() * 500);
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-repro-'));
const proc = spawn(exe, ['--headless=new', '--remote-debugging-port=' + port, '--user-data-dir=' + profile, '--use-angle=swiftshader',
  '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--autoplay-policy=no-user-gesture-required', '--window-size=720,960', 'about:blank'], { stdio: 'ignore' });
const log = { face: cfg.face, source: 'components/ar/faceTrackerHtml.ts (working tree)', errors: [], trials: [] };
let ws, id = 1; const pend = new Map();
const send = (method, params = {}) => new Promise((res) => { const i = id++; pend.set(i, { res }); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 300)); return r.result.value; };
try {
  let tabs; for (let i = 0; i < 60 && !tabs; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); } catch { await sleep(500); } }
  ws = new WebSocket(tabs.find((t) => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener('open', r));
  ws.addEventListener('message', (m) => { const d = JSON.parse(m.data); if (d.id && pend.has(d.id)) { pend.get(d.id).res(d.result || {}); pend.delete(d.id); }
    if (d.method === 'Runtime.exceptionThrown') log.errors.push(JSON.stringify(d.params.exceptionDetails).slice(0, 300)); });
  await send('Runtime.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 720, height: 960, deviceScaleFactor: 1, mobile: false });
  await send('Page.addScriptToEvaluateOnNewDocument', { source: FAKE });
  const t0 = Date.now(); await send('Page.navigate', { url });
  let ok = false;
  while (Date.now() - t0 < 120000 && !ok) {
    await sleep(500);
    for (const m of JSON.parse(await ev('JSON.stringify(window.__msgs ? window.__msgs.splice(0) : [])'))) { const d = JSON.parse(m); if (d.type === 'status' && d.status === 'tracking') ok = true; }
  }
  if (!ok) throw new Error('never tracked');
  log.timeToTrackingMs = Date.now() - t0;
  await sleep(5000);
  await ev("Object.assign(window.__TUNING,{lightEveryMs:1e12,segmentEveryMs:1e12,segmentEveryMsAuto:1e12}); window.__T0=JSON.parse(JSON.stringify(window.__TUNING)); window.__M0=JSON.parse(JSON.stringify(window.__MAT)); true");
  await sleep(3000);
  const rect = await ev("(()=>{const r=document.getElementById('canvas').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,scale:1}})()");
  const shot = async (name) => { const s = await send('Page.captureScreenshot', { format: 'png', clip: rect }); fs.writeFileSync(path.join(outDir, name + '.png'), Buffer.from(s.data, 'base64')); };
  const msg = (lip) => JSON.stringify({ type: 'makeup', makeup: { lip, blush: null, eyeshadow: null } });
  await ev(`window.__kb.receive(${JSON.stringify(msg(null))}); true`); await sleep(1000); await shot('off');
  for (const t of cfg.trials) {
    // restore defaults in place (the page holds references to these objects), then apply this trial only
    // keys a previous trial added (not in the defaults) are deleted too: 11-23 bug, a new field such as glossScale stayed set
    // for every later trial of the same finish
    await ev(`(()=>{for(const k of Object.keys(window.__TUNING)) if(!(k in window.__T0)) delete window.__TUNING[k];
      for(const k of Object.keys(window.__T0)) window.__TUNING[k]=JSON.parse(JSON.stringify(window.__T0[k]));
      for(const k of Object.keys(window.__M0)) { for(const f of Object.keys(window.__MAT[k])) if(!(f in window.__M0[k])) delete window.__MAT[k][f];
        Object.assign(window.__MAT[k], window.__M0[k]); }
      Object.assign(window.__TUNING, ${JSON.stringify(t.tuning || {})});
      const m=${JSON.stringify(t.materials || {})}; for(const k of Object.keys(m)) Object.assign(window.__MAT[k], m[k]); return true;})()`);
    await ev(`window.__kb.receive(${JSON.stringify(msg(null))}); true`); await sleep(300);
    await ev(`window.__kb.receive(${JSON.stringify(msg(t.lip))}); true`); await sleep(1500);
    await shot(t.name);
    log.trials.push(t);
  }
  log.ok = true;
} catch (e) { log.ok = false; log.error = String(e.message || e); console.log('AR TUNE RENDER ERROR', log.error); }
finally {
  fs.writeFileSync(path.join(outDir, 'render_log.json'), JSON.stringify(log, null, 1));
  try { ws && ws.close(); } catch {}
  try { spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' }); } catch { proc.kill(); }
  server.close(); await sleep(1500);
  for (const d of [profile, build]) { try { fs.rmSync(d, { recursive: true, force: true }); } catch {} }
  console.log(JSON.stringify({ ok: log.ok, error: log.error, trials: log.trials.length, errors: log.errors.length }));
  process.exit(0);
}
