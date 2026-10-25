import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, copyFileSync } from 'node:fs';
import { resolve, relative, isAbsolute, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = fileURLToPath(new URL('../', import.meta.url));
const target = resolve(root, 'modules/skin-analysis/android/src/main/assets/skin');
const sha = data => createHash('sha256').update(data).digest('hex');

export function validateAssets(directory) {
  const manifest = JSON.parse(readFileSync(resolve(directory, 'manifest.json'), 'utf8'));
  if (manifest.schema !== 'skin-analysis-assets-v1' || manifest.precision !== 'float32' ||
      manifest.preprocessing !== 'skin-preprocessing-v1' || manifest.models?.length !== 4 ||
      new Set(manifest.models.map(m => m.indicator)).size !== 4 ||
      !['acne', 'pore', 'pigmentation', 'wrinkle'].every(k => manifest.models.some(m => m.indicator === k))) {
    throw new Error('Unsupported or incomplete skin model manifest');
  }
  const required = ['face.xml', 'fixtures.json', ...manifest.models.map(m => m.file)];
  if (required.some(name => !manifest.assets[name])) throw new Error('Manifest is missing required assets');
  for (const [name, expected] of Object.entries(manifest.assets)) {
    if (name !== basename(name) || isAbsolute(name) || sha(readFileSync(resolve(directory, name))) !== expected) {
      throw new Error(`Invalid skin asset: ${name}`);
    }
  }
  for (const model of manifest.models) {
    if (model.sha256 !== manifest.assets[model.file] || JSON.stringify(model.inputShape) !== '[1,3,256,256]' ||
        !/^[a-f0-9]{64}$/.test(model.sourceSha256) || !Array.isArray(model.expectedLogits) ||
        model.expectedLogits.length !== model.outputs || model.expectedLogits.some(v => !Number.isFinite(v)) ||
        !manifest.assets[model.fixture] || model.input !== 'image' || model.output !== 'logits' ||
        model.outputs !== (model.indicator === 'acne' ? 1 : model.indicator === 'wrinkle' ? 7 : 6) ||
        (model.indicator === 'acne' && !(model.threshold > 0 && model.threshold < 1))) {
      throw new Error(`Invalid model contract: ${model.indicator}`);
    }
  }
  return manifest;
}

export function prepareAssets(source) {
  const manifest = validateAssets(source);
  mkdirSync(target, { recursive: true });
  // Only files named in the validated manifest are copied; no dataset is included.
  for (const name of Object.keys(manifest.assets)) copyFileSync(resolve(source, name), resolve(target, name));
  copyFileSync(resolve(source, 'manifest.json'), resolve(target, 'manifest.json'));
  validateAssets(target);
  console.log(`Skin assets ready: ${manifest.bundleVersion}`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const command = process.argv[2];
    if (command === 'prepare') {
      const env = { ...process.env, UV_CACHE_DIR: resolve(root, 'ml/.uv-cache') };
      const result = spawnSync('uv', ['run', '--locked', '--project', 'ml', '--group', 'mobile-export',
        'python', '-m', 'skin_analysis.mobile_export'], { cwd: root, env, encoding: 'utf8', stdio: ['inherit', 'pipe', 'inherit'] });
      if (result.error || result.status !== 0) throw result.error || new Error('Mobile model export failed');
      const source = resolve(result.stdout.trim().split(/\r?\n/).at(-1));
      const rel = relative(resolve(root, 'ml/runs/skin-mobile'), source);
      if (isAbsolute(rel) || rel.startsWith('..')) throw new Error('Unexpected model export directory');
      prepareAssets(source);
    } else if (command === 'validate' || (process.env.EXPO_PUBLIC_ENABLE_SKIN_ANALYSIS === '1' && process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE === 'on-device')) {
      if (!existsSync(resolve(target, 'manifest.json'))) throw new Error('Run npm run skin:prepare before building skin analysis');
      validateAssets(target);
      console.log('Skin asset hashes and contracts verified.');
    }
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
