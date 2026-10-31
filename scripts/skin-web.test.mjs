import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { createPreprocessor, detectRegions, inputCrop } from '../modules/skin-analysis/web/preprocessing.mjs';
import { createJpegRoundTrip } from '../modules/skin-analysis/web/jpeg.mjs';
import { CaptureGate, previewFace } from '../modules/skin-analysis/web/gate.mjs';
import { decodeGrade, meanSkinType, validateModelManifest } from '../modules/skin-analysis/web/model-contract.mjs';

const require = createRequire(import.meta.url);
const assets = resolve('modules/skin-analysis/android/src/main/assets/skin');
const manifest = JSON.parse(readFileSync(resolve(assets, 'manifest.json')));
validateModelManifest(manifest);
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

test('only four v3 models run with WASM CPU and preserve source logits and decoded results', { timeout: 240000 }, async () => {
  assert.deepEqual(manifest.models.map(model => model.indicator), ['pore', 'pigmentation', 'wrinkle', 'skinType']);
  assert.equal(Object.keys(manifest.assets).some(name => name.includes('acne')), false);
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
      if (model.indicator === 'skinType') assert.equal(best(actual), best(model.expectedLogits));
      else assert.equal(decodeGrade(actual[0], model.maxGrade), decodeGrade(model.expectedLogits[0], model.maxGrade));
      console.log(`${model.indicator}: WASM reference logits and decision matched`);
    } finally { input.dispose(); if (output) Object.values(output).forEach(value => value.dispose()); await session.release(); }
  }
});

test('v3 grades use sigmoid and half-up rounding; skin type averages per-ROI softmax', () => {
  assert.equal(decodeGrade(0, 5), 3);
  assert.equal(decodeGrade(-1000, 5), 0);
  assert.equal(decodeGrade(1000, 6), 6);
  const prediction = meanSkinType([[1000, 1000, 1000], [0, 0, 2], [0, 0, 2]]);
  assert.equal(prediction.label, 'oily');
  assert.ok(Math.abs(prediction.probabilities.reduce((a, b) => a + b, 0) - 1) < 1e-12);
  assert.ok(Math.abs(prediction.probabilities[2] - (1 / 3 + 2 * Math.exp(2) / (2 + Math.exp(2))) / 3) < 1e-12);
  assert.throws(() => meanSkinType([[1, 2, 3]]), /model/);
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

function captureAfterHolding(face) {
  const gate = new CaptureGate(); gate.reset();
  let state;
  for (const at of [0, 300, 600, 900, 1200, 1500]) state = gate.update([face], at);
  return state;
}

test('automatic capture accepts faces fitting the visible guide across preview aspect ratios', () => {
  // Same physical face (width / height = .72) in tall and short camera previews.
  // Fit its forehead and chin in the displayed guide, rather than requiring a fixed width.
  for (const [width, height] of [[360, 640], [360, 480], [360, 360], [360, 280]]) {
    const faceHeight = Math.min(height * .60, width * .68 / .72);
    const normalizedHeight = faceHeight / height;
    const face = { cx: .5, cy: .46, width: faceHeight * .72 / width,
      top: .46 - normalizedHeight / 2, bottom: .46 + normalizedHeight / 2, frontal: true };
    assert.deepEqual(captureAfterHolding(face), { guidance: 'hold', progress: 1 }, `${width}x${height}`);
  }
  assert.deepEqual(captureAfterHolding({ cx: .5, cy: .46, width: .70, top: .12, bottom: .80, frontal: true }),
    { guidance: 'hold', progress: 1 });
});

test('automatic capture still rejects small, clipped, and off-center faces', () => {
  const face = { cx: .5, cy: .46, width: .5, top: .18, bottom: .74, frontal: true };
  for (const invalid of [
    { ...face, width: .20, top: .34, bottom: .58 },
    { ...face, width: .85 },
    { ...face, top: .02, bottom: .72 },
    { ...face, top: .22, bottom: .92 },
    { ...face, cx: .72 },
  ]) assert.equal(captureAfterHolding(invalid).progress, 0);
});

test('preview coordinates follow the mirrored cover crop used by the camera', () => {
  const points = Array.from({ length: 478 }, () => ({ x: .5, y: .5 }));
  points[10] = { x: .5, y: .16 }; points[152] = { x: .5, y: .76 };
  points[234] = { x: .25, y: .46 }; points[454] = { x: .75, y: .46 };
  points[33] = { x: .38, y: .38 }; points[263] = { x: .62, y: .38 }; points[1] = { x: .5, y: .54 };
  for (const [width, height] of [[360, 640], [360, 480], [360, 360], [360, 280]]) {
    // Construct source landmarks which cover exactly the visible guide after cropping.
    const scale = Math.max(width / 720, height / 960);
    const projected = points.map(p => ({
      x: (p.x * width + (720 * scale - width) / 2) / (720 * scale),
      y: (p.y * height + (960 * scale - height) / 2) / (960 * scale),
    }));
    const face = previewFace(projected, 720, 960, width, height);
    assert.ok(Math.abs(face.cx - .5) < 1e-9);
    assert.ok(Math.abs(face.top - .16) < 1e-9);
    assert.ok(Math.abs(face.bottom - .76) < 1e-9);
    assert.equal(captureAfterHolding(face).progress, 1);
    const moved = previewFace(projected.map(p => ({ ...p, x: p.x + .05 })), 720, 960, width, height);
    assert.ok(moved.cx < face.cx, 'front-camera horizontal positions must be mirrored');
  }
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


test('preview coordinates use the exact square crop supplied to model preprocessing', () => {
  assert.deepEqual(inputCrop([20, 30, 60, 50], 100, 100), [20, 20, 60, 60]);
  assert.deepEqual(inputCrop([0, 0, 10, 30], 50, 50), [0, 0, 20, 30]);
  assert.throws(() => inputCrop([0, 0, 0, 0], 50, 50), /photo/);
});
