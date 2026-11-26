// Step 5 simulation: the real AR page (a variant built in the scratchpad, repo untouched) in headless Edge with a still face
// clip; screenshots bare + each makeup set (HUD off), then the HUD perf line. node render_cmp.mjs <page> <y4m> <outDir> <label>
import { spawn } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';

const [, , pageFile, y4m, outDir, label] = process.argv;
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const port = 9300 + Math.floor(Math.random() * 500);
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-repro-'));
fs.mkdirSync(outDir, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const proc = spawn(EDGE, [
  '--headless=new', '--remote-debugging-port=' + port, '--user-data-dir=' + profile,
  '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--use-file-for-fake-video-capture=' + y4m,
  '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--disable-gpu-sandbox', '--allow-file-access-from-files',
  '--autoplay-policy=no-user-gesture-required', '--window-size=720,960', 'about:blank',
], { stdio: 'ignore' });
async function getJson(url) {
  for (let i = 0; i < 60; i++) { try { return await (await fetch(url)).json(); } catch (e) { await sleep(500); } }
  throw new Error('no devtools');
}
let ws, nextId = 1; const pending = new Map(); const exceptions = [];
const send = (method, params = {}) => new Promise((resolve, reject) => { const id = nextId++; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method, params })); });
async function evalJs(expression) {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result.value;
}
async function shot(name) {
  const r = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(outDir, label + '_' + name + '.png'), Buffer.from(r.data, 'base64'));
}
const SETS = {
  A: { lip: { hex: '#B5485A', intensity: 0.8, texture: 'matte' }, eyeshadow: { hex: '#9A6A5C', intensity: 0.6, texture: 'glitter', geometry: { shadowFinish: 'glitter' } }, highlighter: { hex: '#F5E1C4', intensity: 0.8, texture: 'shimmer' } },
  B: { lip: { hex: '#C0566A', intensity: 0.7, texture: 'glossy' }, eyeshadow: { hex: '#B08A70', intensity: 0.6, texture: 'shimmer', geometry: { shadowFinish: 'shimmer' } }, highlighter: { hex: '#F2DCC4', intensity: 0.8, texture: 'glossy' } },
  C: { eyeshadow: { hex: '#A0785A', intensity: 0.6, texture: 'metallic', geometry: { shadowFinish: 'metallic' } } },
  D: { eyeshadow: { hex: '#8C5A50', intensity: 0.6, texture: 'glossy', geometry: { shadowFinish: 'glossy' } } },
};
const EMPTY = { lip: null, blush: null, eyeshadow: null, eyeliner: null, mascara: null, highlighter: null, brow: null, foundation: null, contour: null };
try {
  const tab = (await getJson('http://127.0.0.1:' + port + '/json')).find((t) => t.type === 'page');
  ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result); return; }
    if (m.method === 'Runtime.exceptionThrown') exceptions.push(JSON.stringify(m.params.exceptionDetails).slice(0, 400));
  };
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 360, height: 480, deviceScaleFactor: 2, mobile: true });
  await send('Page.addScriptToEvaluateOnNewDocument', { source: 'window.__posted = []; window.ReactNativeWebView = { postMessage: function (t) { window.__posted.push(t); } };' });
  await send('Page.navigate', { url: 'file:///' + pageFile.replace(/\\/g, '/') });
  let tracking = false;
  for (let i = 0; i < 300 && !tracking; i++) {
    await sleep(500);
    const posted = await evalJs('window.__posted');
    tracking = posted.some((t) => t.includes('"status":"tracking"'));
    if (posted.some((t) => t.includes('"status":"unavailable"'))) throw new Error('camera/model unavailable');
  }
  if (!tracking) throw new Error('never tracked');
  await sleep(14000);   // light estimate + first segmenter result (~9 s per call in headless)
  await shot('bare');
  let seq = 1;
  for (const [k, set] of Object.entries(SETS)) {
    const makeup = { ...EMPTY, ...set };
    await evalJs('window.dispatchEvent(new MessageEvent("message", { data: ' + JSON.stringify(JSON.stringify({ type: 'makeup', stateSeq: ++seq, makeup })) + ' }))');
    await sleep(5000);
    await shot(k);
  }
  await evalJs("document.dispatchEvent(new MouseEvent('dblclick'))");
  await sleep(1500);
  const hud = await evalJs("document.getElementById('hud').textContent");
  const lines = hud.split(String.fromCharCode(10)).filter((l) => /^(fps|perf|light ms|strength|env|tone)/.test(l));
  fs.writeFileSync(path.join(outDir, label + '_hud.json'), JSON.stringify({ exceptions, lines }, null, 1));
  console.log(label, 'exc', exceptions.length, lines.filter((l) => /^(fps|perf|strength)/.test(l)).join(' || ').slice(0, 400));
} catch (e) {
  console.log('REPRO ERROR ' + label + ' ' + e.message);
} finally {
  try { ws && ws.close(); } catch (e) { /* ignore */ }
  try { spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' }); } catch (e) { proc.kill(); }
  await sleep(1500);
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) { /* ignore */ }
  process.exit(0);
}
