/** Local research launcher: shared ephemeral auth, CPU inference, no local config edits. */
import { spawn, spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync } from 'node:fs';
import { createServer } from 'node:net';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const root = fileURLToPath(new URL('../', import.meta.url));
const bundle = resolve(root, process.env.NIA_EVAL_BUNDLE ||
  'ml/runs/nia-smartphone-sam-seed-42/recommendation-bundle');
const children = new Set();
let stopping = false;

function stop(code) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (process.platform === 'win32') {
      // Only terminate process trees created by this launcher.
      spawnSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], { stdio: 'ignore' });
    } else {
      try { process.kill(-child.pid, 'SIGTERM'); } catch { /* Child already exited. */ }
    }
  }
  process.exit(code);
}

function launch(command, args, env) {
  const child = spawn(command, args, {
    cwd: root, env, stdio: 'inherit', detached: process.platform !== 'win32',
  });
  child.once('error', (error) => {
    console.error(`Unable to start ${command}: ${error.message}`);
    stop(1);
  });
  child.once('exit', (code) => {
    children.delete(child);
    if (!stopping) stop(code ?? 1);
  });
  children.add(child);
  return child;
}

function portNumber(value) {
  if (!/^\d+$/.test(value) || Number(value) < 1024 || Number(value) > 65535) {
    throw new Error('Ports must be integers between 1024 and 65535.');
  }
  return Number(value);
}

async function requireFreePort(port) {
  await new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once('error', () => reject(new Error(
      `Port ${port} is occupied. Stop the existing server or set NIA_EVAL_PORT / NIA_WEB_PORT.`,
    )));
    server.listen(port, '127.0.0.1', () => server.close(resolvePort));
  });
}

async function main() {
  if (!existsSync(resolve(bundle, 'manifest.json'))) {
    throw new Error(`Download the complete recommendation-bundle folder to:\n${bundle}\n` +
      'See reports/skin-analysis/model-handoff.md');
  }
  const expo = resolve(root, 'node_modules/expo/bin/cli');
  if (!existsSync(expo)) throw new Error('Run npm ci first.');
  const probe = spawnSync('uv', ['--version'], { stdio: 'ignore' });
  if (probe.error || probe.status !== 0) throw new Error('Install uv and reopen the terminal first.');
  const servicePort = portNumber(process.env.NIA_EVAL_PORT || '8765');
  const webPort = portNumber(process.env.NIA_WEB_PORT || '8083');
  if (servicePort === webPort) throw new Error('Service and web ports must differ.');
  await Promise.all([requireFreePort(servicePort), requireFreePort(webPort)]);
  const env = {
    ...process.env,
    NODE_ENV: 'development',
    NIA_EVAL_BUNDLE: bundle,
    NIA_EVAL_PORT: String(servicePort),
    NIA_EVAL_TOKEN: randomBytes(32).toString('hex'),
    NIA_EVAL_DEVICE: 'cpu',
    CUDA_VISIBLE_DEVICES: '-1',
    PYTHONUNBUFFERED: '1',
  };
  console.log('Preparing the locked Python environment and validating four model hashes (CPU).');
  launch('uv', ['run', '--locked', '--project', 'ml', 'python', '-m', 'server.nia.service'], env);
  // First uv run may download Python and dependencies; allow up to 15 minutes.
  const deadline = Date.now() + 15 * 60_000;
  let ready = false;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${servicePort}/status`, {
        headers: { 'X-NIA-Token': env.NIA_EVAL_TOKEN }, signal: AbortSignal.timeout(2000),
      });
      if (response.ok) {
        const status = await response.json();
        if (Object.keys(status.errors).length || status.models.length !== 3 ||
            status.models.some((model) => !model.present) || !status.acne.present) {
          throw new Error('The four-model bundle is incomplete or invalid.');
        }
        ready = true;
        break;
      }
    } catch (error) {
      if (error.message === 'The four-model bundle is incomplete or invalid.') throw error;
    }
    await delay(500);
  }
  if (!ready) throw new Error('Python service startup timed out. Check the error output above.');
  console.log(`Models verified. Open http://localhost:${webPort}/dev/nia after Metro is ready.`);
  console.log('Ctrl+C stops both servers. No .env or config.local.json edits are required.');
  launch(process.execPath, [expo, 'start', '--web', '--localhost', '--port', String(webPort)], env);
}

process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));
main().catch((error) => { console.error(error.message); stop(1); });
