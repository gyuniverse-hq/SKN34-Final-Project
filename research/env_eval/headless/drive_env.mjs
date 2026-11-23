// 11-19 env variant of research/ar_repro/drive.mjs: no makeup; records the env / light HUD lines once a second and the
// posted 'env' messages. Usage: node drive_env.mjs <page.html> <clip.y4m> <outDir> <label> [waitMs]
// Drives the real AR page in headless Edge like a phone WebView: fake camera (a still face), CPU throttling, the shading colour
// injected through the same `message` path the app uses, then frame gaps, screenshots, the HUD and console output are collected.
import { spawn } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';

const [, , pageFile, y4m, outDir, label, waitArg] = process.argv;
const throttle = 1;
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
  // 4-a: pixel width of the two short HUD lines against a 360 px phone-wide view (the HUD starts at 8 px + 8 px padding)
  log.lineWidths = await evalJs("(function () { var h = document.getElementById('hud'), c = document.createElement('canvas').getContext('2d'); c.font = getComputedStyle(h).font; return h.textContent.split(String.fromCharCode(10)).slice(0, 2).map(function (l) { return Math.round(c.measureText(l).width) + 16; }); })()");
  const t0e = await evalJs('performance.now()');
  const hudLines = [];
  const waitMs = Number(waitArg || 14000);
  for (let w = 0; w < waitMs; w += 1000) {
    await sleep(1000);
    const h = await evalJs("document.getElementById('hud').textContent");
    hudLines.push(h.split(String.fromCharCode(10)).filter((l) => /^(low|exp t|env|wb|light ms|fps|tone|cam|perf|expo|skinrb)/.test(l)).join(' || '));
  }
  const posted = await evalJs('window.__posted');
  const env = posted.filter((p) => p[1].includes('"type":"env"')).map((p) => [Math.round(p[0] - t0e), p[1]]);
  const summary = { label, timeToTrackingMs: log.timeToTrackingMs, exceptions: log.exceptions, lineWidths: log.lineWidths, env, hud: hudLines };
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
