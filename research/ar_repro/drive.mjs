// Drives the real AR page in headless Edge like a phone WebView: fake camera (a still face), CPU throttling, the shading colour
// injected through the same `message` path the app uses, then frame gaps, screenshots, the HUD and console output are collected.
import { spawn } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';

const [, , pageFile, y4m, outDir, throttleArg, label, shadeArg] = process.argv;
const throttle = Number(throttleArg || 4);
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
  for (let i = 0; i < 60; i++) {
    try { return await (await fetch(url)).json(); } catch (e) { await sleep(500); }
  }
  throw new Error('no devtools at ' + url);
}

const log = { console: [], exceptions: [], posted: [] };
let ws, nextId = 1;
const pending = new Map();
function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}
async function evalJs(expression) {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result.value;
}
async function shot(name) {
  const r = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(outDir, label + '_' + name + '.png'), Buffer.from(r.data, 'base64'));
}

try {
  const tabs = await getJson('http://127.0.0.1:' + port + '/json');
  const tab = tabs.find((t) => t.type === 'page');
  ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result); return; }
    if (m.method === 'Runtime.consoleAPICalled') log.console.push(m.params.type + ': ' + m.params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300));
    if (m.method === 'Runtime.exceptionThrown') log.exceptions.push(JSON.stringify(m.params.exceptionDetails).slice(0, 500));
  };
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 360, height: 480, deviceScaleFactor: 2, mobile: true });
  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `window.__posted = []; window.ReactNativeWebView = { postMessage: function (t) { window.__posted.push([performance.now(), t]); } };
      window.__frames = []; (function loop() { window.__frames.push(performance.now()); requestAnimationFrame(loop); })();`,
  });
  await send('Emulation.setCPUThrottlingRate', { rate: throttle });
  const t0 = Date.now();
  await send('Page.navigate', { url: 'file:///' + pageFile.replace(/\\/g, '/') });

  // wait until the face is tracked
  let tracking = false;
  for (let i = 0; i < 300 && !tracking; i++) {
    await sleep(500);
    const posted = await evalJs('window.__posted.map(function (p) { return p[1]; })');
    tracking = posted.some((t) => t.includes('"status":"tracking"'));
    if (posted.some((t) => t.includes('"status":"unavailable"') || t.includes('"status":"denied"'))) { log.posted = posted; throw new Error('camera/model unavailable: ' + posted.filter((t) => t.includes('status')).join(' ')); }
  }
  log.timeToTrackingMs = Date.now() - t0;
  if (!tracking) throw new Error('never tracked');
  await sleep(2500);   // let the page settle: light estimate, first segmenter run
  await evalJs("document.dispatchEvent(new MouseEvent('dblclick'))");   // HUD on
  const hudBefore = await evalJs("document.getElementById('hud').textContent");
  await evalJs("document.getElementById('hud').style.visibility = 'hidden'");   // text keeps updating; only the pixels are hidden
  await shot('0_before');

  // choose the shading colour (the app sends the whole makeup state)
  const makeup = { lip: null, blush: null, eyeshadow: null, eyeliner: null, mascara: null, highlighter: null, brow: null, foundation: null,
    contour: shadeArg === 'none' ? null : { hex: '#7a4e3c', intensity: 0.85, geometry: {} } };
  const injectAt = await evalJs('(function () { var t = performance.now(); window.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({ type: "makeup", stateSeq: 1, makeup: ' + JSON.stringify(makeup) + ' }) })); return t; })()');
  const waits = [300, 700, 1500, 3000, 6000];
  let prev = 0;
  for (const w of waits) {
    await sleep(w - prev); prev = w;
    await shot('1_after_' + w);
  }
  const hudAfter = await evalJs("document.getElementById('hud').textContent");
  const frames = await evalJs('window.__frames');
  const posted = await evalJs('window.__posted');
  const win = frames.filter((t) => t >= injectAt - 300 && t <= injectAt + 6000);
  let maxGap = 0, maxGapAt = 0;
  for (let i = 1; i < win.length; i++) { const g = win[i] - win[i - 1]; if (g > maxGap) { maxGap = g; maxGapAt = win[i] - injectAt; } }
  log.posted = posted.map((p) => [Math.round(p[0] - injectAt), p[1].slice(0, 160)]).filter((p) => !p[1].includes('"type":"light'));
  const summary = {
    label, throttle, timeToTrackingMs: log.timeToTrackingMs,
    maxMainThreadGapMs: Math.round(maxGap), maxGapAtMsAfterInject: Math.round(maxGapAt), frameCountWindow: win.length,
    exceptions: log.exceptions, consoleErrors: log.console.filter((c) => /error|warn/i.test(c)).slice(0, 12),
    crash: posted.some((p) => p[1].includes('"type":"crash"')),
    postedAfterInject: log.posted.slice(0, 30),
    hudBefore: hudBefore.split('\n').filter((l) => /^(fps|jaw|found|occ)/.test(l)),
    hudAfter: hudAfter.split('\n').filter((l) => /^(fps|jaw|found|occ)/.test(l)),
  };
  fs.writeFileSync(path.join(outDir, label + '_summary.json'), JSON.stringify(summary, null, 1));
  console.log(JSON.stringify(summary, null, 1));
} catch (e) {
  console.log('REPRO ERROR ' + e.message);
  fs.writeFileSync(path.join(outDir, label + '_error.json'), JSON.stringify({ error: e.message, log }, null, 1));
} finally {
  try { ws && ws.close(); } catch (e) { /* ignore */ }
  // headless Edge leaves renderer / GPU children behind: kill the whole tree, then the profile
  try { spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' }); } catch (e) { proc.kill(); }
  await sleep(1500);
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) { /* ignore */ }
  process.exit(0);
}
