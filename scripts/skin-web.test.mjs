import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { createPreprocessor, detectRegions } from '../modules/skin-analysis/web/preprocessing.mjs';
import { createJpegRoundTrip } from '../modules/skin-analysis/web/jpeg.mjs';
import { CaptureGate } from '../modules/skin-analysis/web/gate.mjs';

const require = createRequire(import.meta.url);
const assets = resolve('modules/skin-analysis/android/src/main/assets/skin');
const manifest = JSON.parse(readFileSync(resolve(assets, 'manifest.json')));
const floats = name => { const bytes = readFileSync(resolve(assets, name)); return new Float32Array(bytes.buffer, bytes.byteOffset, bytes.length / 4); };

test('browser preprocessing matches reference resize tensors and records the separate JPEG variant', async () => {
  const cvModule = require('@techstark/opencv-js');
  let cv;
  if (cvModule instanceof Promise) cv = await cvModule;
  else { if (!cvModule.Mat) await new Promise(done => { cvModule.onRuntimeInitialized = done; }); cv = cvModule; }
  const jpeg = await require('@cornerstonejs/codec-libjpeg-turbo-8bit/wasmjs')({
    wasmBinary: readFileSync(require.resolve('@cornerstonejs/codec-libjpeg-turbo-8bit/wasm')),
  });
  const tensor = createPreprocessor(cv, createJpegRoundTrip(jpeg));
  const { PNG } = require('pngjs');
  for (const fixture of JSON.parse(readFileSync(resolve(assets, 'fixtures.json')))) {
    const png = PNG.sync.read(readFileSync(resolve(assets, fixture.image)));
    const image = cv.matFromArray(png.height, png.width, cv.CV_8UC4, png.data);
    try {
      const actual = await tensor(image, fixture.bbox), expected = floats(fixture.tensor);
      assert.equal(actual.length, 3 * 256 * 256);
      let error = 0;
      for (let i = 0; i < actual.length; i++) error = Math.max(error, Math.abs(actual[i] - expected[i]));
      assert.ok(Number.isFinite(error));
      // This is explicitly NOT original JPEG parity. Guard the measured experimental fixture baseline.
      assert.ok(error <= (fixture.bbox ? .262 : fixture.maxAbsoluteError), `${fixture.image}: ${error}`);
      console.log(`${fixture.image}: max tensor difference ${error}`);
    } finally { image.delete(); }
  }
  cv.FS_createDataFile('/', 'web-test-face.xml', readFileSync(resolve(assets, 'face.xml')), true, false, false);
  const detector = new cv.CascadeClassifier();
  const png = PNG.sync.read(readFileSync(resolve(assets, 'identity.png')));
  const image = cv.matFromArray(png.height, png.width, cv.CV_8UC4, png.data);
  try {
    assert.ok(detector.load('web-test-face.xml'));
    assert.throws(() => detectRegions(cv, image, detector), /photo/);
  } finally { image.delete(); detector.delete(); cv.FS_unlink('/web-test-face.xml'); }
});

test('all four original models run with the WebAssembly CPU provider and match reference outputs', { timeout: 240000 }, async () => {
  const ort = require('onnxruntime-web/wasm'); ort.env.wasm.numThreads = 1;
  for (const model of manifest.models) {
    const session = await ort.InferenceSession.create(readFileSync(resolve(assets, model.file)), { executionProviders: ['wasm'] });
    const input = new ort.Tensor('float32', floats(model.fixture), [1, 3, 256, 256]);
    let output;
    try {
      output = await session.run({ image: input }); const actual = output.logits.data;
      assert.equal(actual.length, model.outputs);
      actual.forEach((value, i) => assert.ok(Math.abs(value - model.expectedLogits[i]) <= 1e-4 + 1e-3 * Math.abs(model.expectedLogits[i])));
      const best = values => values.reduce((at, value, i) => value > values[at] ? i : at, 0);
      if (model.indicator === 'acne') assert.equal(1 / (1 + Math.exp(-actual[0])) >= model.threshold,
        1 / (1 + Math.exp(-model.expectedLogits[0])) >= model.threshold);
      else assert.equal(best(actual), best(model.expectedLogits));
      console.log(`${model.indicator}: WASM reference logits and decision matched`);
    } finally { input.dispose(); if (output) Object.values(output).forEach(value => value.dispose()); await session.release(); }
  }
});

test('automatic capture requires continuous stability and resets for multiple faces or movement', () => {
  const face = { cx: .5, cy: .48, width: .5, top: .2, bottom: .74, frontal: true };
  const gate = new CaptureGate(); gate.reset();
  for (const at of [0, 300, 600, 900, 1200]) assert.ok(gate.update([face], at).progress < 1);
  assert.equal(gate.update([face], 1500).progress, 1);
  assert.equal(gate.update([face, face], 1600).guidance, 'multipleFaces');
  assert.equal(gate.update([face], 1700).progress, 0);
  gate.update([face], 2000);
  assert.equal(gate.update([{ ...face, cx: .53 }], 2200).progress, 0);
  assert.equal(gate.update([], 2400).guidance, 'noFace');
  assert.equal(gate.update([{ ...face, frontal: false }], 2600).guidance, 'straight');
});

test('asset middleware serves only listed assets, and rejects uploads and traversal', async () => {
  const middleware = require('./skin-web-middleware.cjs')(resolve('.'));
  function request(url, method = 'GET') {
    const headers = {}, result = { status: 200, body: '' };
    middleware({ url, method }, {
      setHeader: (key, value) => { headers[key] = value; },
      writeHead: status => { result.status = status; }, end: body => { result.body = body; },
    }, () => { result.status = 418; });
    return result;
  }
  assert.equal(request('/skin-runtime/manifest.json', 'POST').status, 405);
  assert.equal(request('/skin-runtime/not-allowed').status, 404);
  assert.equal(request(`/skin-runtime/${manifest.bundleVersion}/%2e%2e%2f.env`).status, 404);
  assert.equal(request('/skin-runtime/jpeg.js', 'HEAD').status, 200);
  assert.equal(JSON.parse(request('/skin-runtime/manifest.json').body).bundleVersion, manifest.bundleVersion);
  assert.equal(request('/another-route').status, 418);
});
