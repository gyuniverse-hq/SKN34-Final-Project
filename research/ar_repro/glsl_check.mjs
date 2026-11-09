// Opens the shader check page in its own headless Edge (own profile, devtools port) and prints the page's RESULT text.
import { spawn } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';

const page = process.argv[2];
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const port = 9800 + Math.floor(Math.random() * 100);
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-repro-'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const proc = spawn(EDGE, ['--headless=new', '--remote-debugging-port=' + port, '--user-data-dir=' + profile, '--use-angle=swiftshader',
  '--enable-unsafe-swiftshader', '--disable-gpu-sandbox', '--allow-file-access-from-files', 'file:///' + page.replace(/\\/g, '/')], { stdio: 'ignore' });
let out = 'NO RESULT';
try {
  let tabs = null;
  for (let i = 0; i < 40 && !tabs; i++) { try { tabs = await (await fetch('http://127.0.0.1:' + port + '/json')).json(); } catch (e) { await sleep(500); } }
  const tab = tabs.find((t) => t.type === 'page');
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((r) => { ws.onopen = r; });
  let id = 1;
  const ask = (method, params) => new Promise((resolve) => {
    const my = id++;
    const h = (ev) => { const m = JSON.parse(ev.data); if (m.id === my) { ws.removeEventListener('message', h); resolve(m.result); } };
    ws.addEventListener('message', h);
    ws.send(JSON.stringify({ id: my, method, params }));
  });
  for (let i = 0; i < 40; i++) {
    const r = await ask('Runtime.evaluate', { expression: "(document.getElementById('o')||{}).textContent||''", returnByValue: true });
    if (r && r.result && String(r.result.value).startsWith('RESULT')) { out = r.result.value; break; }
    await sleep(500);
  }
  ws.close();
} finally {
  try { spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' }); } catch (e) { proc.kill(); }
  await sleep(1500);
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) { /* ignore */ }
}
console.log(out.split(' | ').join('\n'));
process.exit(0);
