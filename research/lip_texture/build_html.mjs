// Writes the AR page (FACE_TRACKER_HTML) to research/data/lip_texture/page.html for offline renders.
// Transpiles components/ar/faceTrackerHtml.ts and faceUV.ts with the repo's TypeScript (no new deps).
// Run: node research/lip_texture/build_html.mjs
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const require = createRequire(import.meta.url);
const ts = require(join(root, 'node_modules', 'typescript'));
const dataArg = process.argv.indexOf('--data-dir');
if (dataArg >= 0 && !process.argv[dataArg + 1]) throw new Error('--data-dir requires a path');
const dataDir = dataArg >= 0 ? resolve(process.argv[dataArg + 1]) : join(root, 'research', 'data', 'lip_texture');
const tmp = join(dataDir, 'build');
mkdirSync(tmp, { recursive: true });

for (const name of ['faceUV', 'faceTrackerHtml']) {
  const src = readFileSync(join(root, 'components', 'ar', `${name}.ts`), 'utf8');
  const out = ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } });
  writeFileSync(join(tmp, `${name}.js`), out.outputText);
}
const { FACE_TRACKER_HTML } = require(join(tmp, 'faceTrackerHtml.js'));
writeFileSync(join(dataDir, 'page.html'), FACE_TRACKER_HTML);
console.log('page.html', FACE_TRACKER_HTML.length);
