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
    const manifest = { schema: 'skin-analysis-assets-v1', precision: 'float32', preprocessing: 'skin-preprocessing-v1', models: [], assets: {} };
    const asset = name => {
      writeFileSync(join(directory, name), 'fixture');
      manifest.assets[name] = createHash('sha256').update(readFileSync(join(directory, name))).digest('hex');
    };
    ['face.xml', 'fixtures.json', 'input.f32'].forEach(asset);
    for (const indicator of ['acne', 'pore', 'pigmentation', 'wrinkle']) {
      const file = `${indicator}.onnx`; asset(file);
      const outputs = indicator === 'acne' ? 1 : indicator === 'wrinkle' ? 7 : 6;
      manifest.models.push({ indicator, file, sha256: manifest.assets[file], sourceSha256: 'a'.repeat(64),
        input: 'image', output: 'logits', inputShape: [1, 3, 256, 256], outputs,
        expectedLogits: Array(outputs).fill(1), fixture: 'input.f32', threshold: .5 });
    }
    const save = () => writeFileSync(join(directory, 'manifest.json'), JSON.stringify(manifest));
    save(); action(directory, manifest, save);
  } finally { rmSync(directory, { recursive: true }); }
}

test('accepts a complete manifest and blocks modified model files', () => bundle((directory) => {
  assert.equal(validateAssets(directory).models.length, 4);
  writeFileSync(join(directory, 'pore.onnx'), 'corrupted');
  assert.throws(() => validateAssets(directory), /Invalid skin asset/);
}));
test('blocks missing models, invalid thresholds, and paths escaping the asset bundle', () => bundle((directory, manifest, save) => {
  manifest.models[0].threshold = 0; save();
  assert.throws(() => validateAssets(directory), /Invalid model contract/);
  manifest.models[0].threshold = .5;
  manifest.assets['../outside.onnx'] = 'a'.repeat(64); save();
  assert.throws(() => validateAssets(directory), /Invalid skin asset/);
  delete manifest.assets['../outside.onnx'];
  manifest.models.pop(); save();
  assert.throws(() => validateAssets(directory), /incomplete/);
}));
