// Local numeric evaluation only. No images, network, telemetry, or accuracy claims.
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
const source = await readFile(new URL('../lib/skinFusion.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } });
const { fuseSkinType } = await import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
if (!process.argv[2]) throw new Error('Usage: node scripts/evaluate-skin-fusion.mjs input.json');
const rows = JSON.parse(await readFile(process.argv[2], 'utf8'));
if (!Array.isArray(rows)) throw new Error('Expected an array of { prediction?, sosTotal }');
const results = rows.map((row, index) => {
  const fusion = fuseSkinType(row.prediction, row.sosTotal);
  return { index, imageType: row.prediction?.label ?? 'unknown', ...fusion };
});
const paired = results.filter(r => r.scores !== null);
const changes = paired.filter(r => r.changed);
const directions = {}, reasons = {};
for (const r of changes) { const key = `${r.imageType}->${r.type}`; directions[key] = (directions[key] ?? 0) + 1; }
for (const r of results) reasons[r.reason] = (reasons[r.reason] ?? 0) + 1;
console.log(JSON.stringify({ policy: 'sos-oily-v1', sampleCount: rows.length, comparableCount: paired.length,
  changedCount: changes.length, changedRate: paired.length ? changes.length / paired.length : null,
  directions, reasons, meanDelta: paired.length ? [0, 1, 2].map(i => paired.reduce((sum, r) => sum + r.delta[i], 0) / paired.length) : null,
  note: 'Rule comparison only; not a measurement of classification accuracy.', results }, null, 2));
