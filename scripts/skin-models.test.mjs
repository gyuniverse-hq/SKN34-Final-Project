import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { selectedSkinModel, preparedSkinModel } from './skin-models.cjs';

function project(action) {
  const root = mkdtempSync(resolve(tmpdir(), 'skin-models-'));
  try { action(root); }
  finally { rmSync(root, { recursive: true }); }
}

test('model selection defaults to v4, reads dotenv precedence and honors an explicit environment', () => project(root => {
  assert.equal(selectedSkinModel(root, {}).name, 'skin-analysis-v4');
  writeFileSync(resolve(root, '.env'), 'SKIN_ANALYSIS_MODEL=skin-analysis-v3\n');
  assert.equal(selectedSkinModel(root, {}).name, 'skin-analysis-v3');
  writeFileSync(resolve(root, '.env.local'), 'SKIN_ANALYSIS_MODEL=skin-analysis-v4\n');
  assert.equal(selectedSkinModel(root, {}).name, 'skin-analysis-v4');
  assert.equal(selectedSkinModel(root, { SKIN_ANALYSIS_MODEL: 'skin-analysis-v3' }).name, 'skin-analysis-v3');
  assert.throws(() => selectedSkinModel(root, { SKIN_ANALYSIS_MODEL: 'typo' }), /Unsupported SKIN_ANALYSIS_MODEL/);
  assert.throws(() => selectedSkinModel(root, { SKIN_ANALYSIS_MODEL: '' }), /Unsupported SKIN_ANALYSIS_MODEL/);
}));

test('each configured model resolves its own prepared bundle and rejects missing or mismatched versions', () => project(root => {
  const cache = resolve(root, 'ml/runs/skin-mobile');
  mkdirSync(cache, { recursive: true });
  const registry = {};
  for (const [suffix, hash] of [['v3', 'a'.repeat(64)], ['v4', 'b'.repeat(64)]]) {
    const name = `skin-analysis-${suffix}`, directory = resolve(cache, hash);
    mkdirSync(directory);
    writeFileSync(resolve(directory, 'manifest.json'), JSON.stringify({
      schema: `skin-analysis-assets-${suffix}`, bundleVersion: hash,
    }));
    registry[name] = hash;
  }
  const save = () => writeFileSync(resolve(cache, 'models.json'), JSON.stringify(registry));
  save();
  for (const name of Object.keys(registry)) {
    assert.equal(preparedSkinModel(root, selectedSkinModel(root, { SKIN_ANALYSIS_MODEL: name })), resolve(cache, registry[name]));
  }
  const v3 = selectedSkinModel(root, { SKIN_ANALYSIS_MODEL: 'skin-analysis-v3' });
  registry[v3.name] = registry['skin-analysis-v4']; save();
  assert.throws(() => preparedSkinModel(root, v3), /Invalid prepared/);
  registry[v3.name] = '../outside'; save();
  assert.throws(() => preparedSkinModel(root, v3), /Missing prepared/);
  delete registry[v3.name]; save();
  assert.throws(() => preparedSkinModel(root, v3), /Missing prepared/);
}));
