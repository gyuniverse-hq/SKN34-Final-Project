const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { parseProjectEnv } = require('@expo/env');

const SKIN_MODELS = Object.freeze({
  'skin-analysis-v3': { exporter: 'skin_analysis.mobile_export_v3', schema: 'skin-analysis-assets-v3' },
  'skin-analysis-v4': { exporter: 'skin_analysis.mobile_export_v4', schema: 'skin-analysis-assets-v4' },
});

function selectedSkinModel(root, systemEnv = process.env) {
  const { env } = parseProjectEnv(root, {
    mode: systemEnv.NODE_ENV === 'production' ? 'production' : 'development', silent: true, systemEnv,
  });
  const name = systemEnv.SKIN_ANALYSIS_MODEL ?? env.SKIN_ANALYSIS_MODEL ?? 'skin-analysis-v4';
  if (!Object.hasOwn(SKIN_MODELS, name)) {
    throw new Error(`Unsupported SKIN_ANALYSIS_MODEL: ${name}. Choose ${Object.keys(SKIN_MODELS).join(' or ')}.`);
  }
  return { name, ...SKIN_MODELS[name] };
}

function preparedSkinModel(root, model = selectedSkinModel(root)) {
  const cache = resolve(root, 'ml/runs/skin-mobile');
  const registry = JSON.parse(readFileSync(resolve(cache, 'models.json'), 'utf8'));
  const version = registry[model.name];
  if (typeof version !== 'string' || !/^[a-f0-9]{64}$/.test(version)) {
    throw new Error(`Missing prepared ${model.name}. Run npm run skin:prepare.`);
  }
  const directory = resolve(cache, version);
  const manifest = JSON.parse(readFileSync(resolve(directory, 'manifest.json'), 'utf8'));
  if (manifest.bundleVersion !== version || manifest.schema !== model.schema) {
    throw new Error(`Invalid prepared ${model.name}. Run npm run skin:prepare.`);
  }
  return directory;
}

module.exports = { SKIN_MODELS, selectedSkinModel, preparedSkinModel };
