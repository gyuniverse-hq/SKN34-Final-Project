import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { validateAssets } from './skin-assets.mjs';

function bundle(action) {
  const directory = mkdtempSync(join(tmpdir(), 'skin-assets-'));
  try {
    const manifest = { schema: 'skin-analysis-assets-v2', bundleVersion: 'c'.repeat(64), precision: 'float32',
      preprocessing: 'skin-preprocessing-v3', roiMethod: 'opencv_haar_facebox_proportions_v1', models: [], assets: {} };
    const asset = name => {
      writeFileSync(join(directory, name), 'fixture');
      manifest.assets[name] = createHash('sha256').update(readFileSync(join(directory, name))).digest('hex');
    };
    ['face.xml', 'fixtures.json', 'input.f32'].forEach(asset);
    for (const indicator of ['acne', 'pore', 'pigmentation', 'wrinkle', 'skinType']) {
      const file = `${indicator}.onnx`; asset(file);
      const outputs = indicator === 'skinType' ? 3 : 1;
      manifest.models.push({ indicator, file, sha256: manifest.assets[file], sourceSha256: 'a'.repeat(64),
        input: 'image', output: 'logits', inputShape: [1, 3, 256, 256], outputs,
        expectedLogits: Array(outputs).fill(1), fixture: 'input.f32', threshold: .5,
        decoder: indicator === 'skinType' ? 'mean_softmax' : 'sigmoid_grade',
        maxGrade: indicator === 'wrinkle' ? 6 : 5, classes: ['dry', 'balanced', 'oily'],
        roiEnhancement: 'pillow-unsharp1-75-contrast1.4-embedded' });
    }
    const save = () => writeFileSync(join(directory, 'manifest.json'), JSON.stringify(manifest));
    save(); action(directory, manifest, save);
  } finally { rmSync(directory, { recursive: true }); }
}

test('accepts a complete manifest and blocks modified model files', () => bundle((directory) => {
  assert.equal(validateAssets(directory).models.length, 5);
  writeFileSync(join(directory, 'pore.onnx'), 'corrupted');
  assert.throws(() => validateAssets(directory), /Invalid skin asset/);
}));
test('blocks missing models, invalid thresholds, and paths escaping the asset bundle', () => bundle((directory, manifest, save) => {
  manifest.models[0].threshold = 0; save();
  assert.throws(() => validateAssets(directory), /model/);
  manifest.models[0].threshold = .5;
  manifest.assets['../outside.onnx'] = 'a'.repeat(64); save();
  assert.throws(() => validateAssets(directory), /Invalid skin asset/);
  delete manifest.assets['../outside.onnx'];
  manifest.models.pop(); save();
  assert.throws(() => validateAssets(directory), /model/);
}));

test('rejects old classifier outputs and incorrect v3 class ordering', () => bundle((directory, manifest, save) => {
  manifest.models[1].outputs = 6; save();
  assert.throws(() => validateAssets(directory), /model/);
  manifest.models[1].outputs = 1;
  manifest.models[4].classes.reverse(); save();
  assert.throws(() => validateAssets(directory), /model/);
}));
