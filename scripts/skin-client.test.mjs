import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, utimesSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const require = createRequire(import.meta.url);

test('on-device assets are served even with the obsolete server setting and photo uploads are rejected', async () => {
  const root = mkdtempSync(join(tmpdir(), 'skin-device-'));
  const web = join(root, 'modules/skin-analysis/web'); mkdirSync(web, { recursive: true });
  const assets = join(root, 'modules/skin-analysis/android/src/main/assets/skin'); mkdirSync(assets, { recursive: true });
  const version = 'a'.repeat(64);
  writeFileSync(join(web, 'runtime.mjs'), 'export const local = true;');
  writeFileSync(join(assets, 'manifest.json'), JSON.stringify({ bundleVersion: version, assets: { 'model.onnx': 'b'.repeat(64) } }));
  writeFileSync(join(assets, 'model.onnx'), 'model');
  const old = process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE;
  process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE = 'server';
  const middleware = require('./skin-web-middleware.cjs')(root);
  const server = createServer((req, res) => middleware(req, res, () => { res.writeHead(404); res.end(); }));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const origin = `http://127.0.0.1:${server.address().port}/skin-runtime/`;
    assert.equal((await fetch(origin + 'runtime.mjs')).status, 200);
    assert.equal((await fetch(origin + 'manifest.json')).status, 200);
    assert.equal((await fetch(origin + version + '/model.onnx')).status, 200);
    assert.equal((await fetch(origin + 'capture.mjs')).status, 404);
    assert.equal((await fetch(origin + 'runtime.mjs', { method: 'POST' })).status, 405);
    // Preparing a new bundle while Metro is running must refresh the cached manifest.
    const nextVersion = 'c'.repeat(64), manifestPath = join(assets, 'manifest.json');
    writeFileSync(manifestPath, JSON.stringify({ bundleVersion: nextVersion, assets: { 'model.onnx': 'b'.repeat(64) } }));
    const future = new Date(Date.now() + 1000); utimesSync(manifestPath, future, future);
    assert.equal((await (await fetch(origin + 'manifest.json')).json()).bundleVersion, nextVersion);
    assert.equal((await fetch(origin + nextVersion + '/model.onnx')).status, 200);
    assert.equal((await fetch(origin + version + '/model.onnx')).status, 404);
  } finally {
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
    if (old === undefined) delete process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE;
    else process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE = old;
    rmSync(root, { recursive: true, force: true });
  }
});
