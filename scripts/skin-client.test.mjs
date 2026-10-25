import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

const require = createRequire(import.meta.url);

test('camera middleware works in a clone with no ML/model assets', async () => {
  const root = mkdtempSync(join(tmpdir(), 'skin-camera-'));
  const web = join(root, 'modules/skin-analysis/web'); mkdirSync(web, { recursive: true });
  writeFileSync(join(web, 'capture.mjs'), 'export const cameraOnly = true;');
  writeFileSync(join(web, 'gate.mjs'), 'export const gate = true;');
  const old = process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE;
  process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE = 'server';
  const middleware = require('./skin-web-middleware.cjs')(root);
  const server = createServer((req, res) => middleware(req, res, () => { res.writeHead(404); res.end(); }));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const origin = `http://127.0.0.1:${server.address().port}/skin-runtime/`;
    assert.equal((await fetch(origin + 'capture.mjs')).status, 200);
    assert.equal((await fetch(origin + 'gate.mjs')).status, 200);
    assert.equal((await fetch(origin + 'manifest.json')).status, 404);
    assert.equal((await fetch(origin + 'acne.onnx')).status, 404);
    assert.equal((await fetch(origin + 'capture.mjs', { method: 'POST' })).status, 405);
  } finally {
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
    if (old === undefined) delete process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE;
    else process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE = old;
  }
});

test('server-mode build checks do not require skin model preparation', () => {
  const result = spawnSync(process.execPath, ['scripts/skin-assets.mjs', 'check-build'], {
    env: { ...process.env, EXPO_PUBLIC_ENABLE_SKIN_ANALYSIS: '1', EXPO_PUBLIC_SKIN_ANALYSIS_MODE: 'server' }, encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stderr);
  const camera = readFileSync('modules/skin-analysis/web/capture.mjs', 'utf8');
  assert.doesNotMatch(camera, /onnx|InferenceSession|createPreprocessor|Authorization|access_token/);
});
