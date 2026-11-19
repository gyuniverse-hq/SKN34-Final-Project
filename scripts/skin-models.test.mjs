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
  writeFileSync(resolve(root, '.env'), 'SKIN_ANALYSIS_MODEL=skin-analysis-v4\n');
  assert.equal(selectedSkinModel(root, {}).name, 'skin-analysis-v4');
  writeFileSync(resolve(root, '.env.local'), 'SKIN_ANALYSIS_MODEL=skin-analysis-v4.1\n');
  assert.equal(selectedSkinModel(root, {}).name, 'skin-analysis-v4.1');
  assert.equal(selectedSkinModel(root, { SKIN_ANALYSIS_MODEL: 'skin-analysis-v4' }).name, 'skin-analysis-v4');
  assert.throws(() => selectedSkinModel(root, { SKIN_ANALYSIS_MODEL: 'skin-analysis-v3' }), /Unsupported skin|Unsupported SKIN/);
  assert.throws(() => selectedSkinModel(root, { SKIN_ANALYSIS_MODEL: 'typo' }), /Unsupported SKIN_ANALYSIS_MODEL/);
  assert.throws(() => selectedSkinModel(root, { SKIN_ANALYSIS_MODEL: '' }), /Unsupported SKIN_ANALYSIS_MODEL/);
}));

test('each configured model resolves its own prepared bundle and rejects missing or mismatched versions', () => project(root => {
  const cache = resolve(root, 'ml/runs/skin-mobile');
  mkdirSync(cache, { recursive: true });
  const registry = {};
  for (const [suffix, hash] of [['v4', 'a'.repeat(64)], ['v4.1', 'b'.repeat(64)]]) {
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
  const v41 = selectedSkinModel(root, { SKIN_ANALYSIS_MODEL: 'skin-analysis-v4.1' });
  registry[v41.name] = registry['skin-analysis-v4']; save();
  assert.throws(() => preparedSkinModel(root, v41), /Invalid prepared/);
  registry[v41.name] = '../outside'; save();
  assert.throws(() => preparedSkinModel(root, v41), /Missing prepared/);
  delete registry[v41.name]; save();
  assert.throws(() => preparedSkinModel(root, v41), /Missing prepared/);
}));
