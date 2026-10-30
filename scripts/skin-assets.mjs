import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, copyFileSync } from 'node:fs';
import { resolve, relative, isAbsolute, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { validateModelManifest } from '../modules/skin-analysis/web/model-contract.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const target = resolve(root, 'modules/skin-analysis/android/src/main/assets/skin');
const sha = data => createHash('sha256').update(data).digest('hex');

export function validateAssets(directory) {
  const manifest = JSON.parse(readFileSync(resolve(directory, 'manifest.json'), 'utf8'));
  validateModelManifest(manifest);
  const required = ['face.xml', 'fixtures.json', ...manifest.models.map(m => m.file)];
  if (required.some(name => !manifest.assets[name])) throw new Error('Manifest is missing required assets');
  for (const [name, expected] of Object.entries(manifest.assets)) {
    if (name !== basename(name) || isAbsolute(name) || sha(readFileSync(resolve(directory, name))) !== expected) {
      throw new Error(`Invalid skin asset: ${name}`);
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
        'python', '-m', 'skin_analysis.mobile_export_v3'], { cwd: root, env, encoding: 'utf8', stdio: ['inherit', 'pipe', 'inherit'] });
      if (result.error || result.status !== 0) throw result.error || new Error('Mobile model export failed');
      const source = resolve(result.stdout.trim().split(/\r?\n/).at(-1));
      const rel = relative(resolve(root, 'ml/runs/skin-mobile'), source);
      if (isAbsolute(rel) || rel.startsWith('..')) throw new Error('Unexpected model export directory');
      prepareAssets(source);
    } else if (command === 'validate' || (command === 'check-build' && process.env.EXPO_PUBLIC_ENABLE_SKIN_ANALYSIS === '1')) {
      if (!existsSync(resolve(target, 'manifest.json'))) throw new Error('Run npm run skin:prepare before building skin analysis');
      validateAssets(target);
      console.log('Skin asset hashes and contracts verified.');
    }
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
