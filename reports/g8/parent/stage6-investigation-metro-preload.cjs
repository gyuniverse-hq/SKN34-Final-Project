// Investigation process only. Product metro.config.js stays byte-identical.
const Module = require('node:module');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const load = Module._load;
Module._load = function(request, parent, isMain) {
  const result = load.apply(this, arguments);
  let file;
  try { file = Module._resolveFilename(request, parent); } catch { return result; }
  if (file === path.join(root, 'metro.config.js')) {
    result.transformer.babelTransformerPath = path.join(__dirname, 'stage6-investigation-transformer.cjs');
    result.cacheVersion = 'g8-investigation-v1';
  }
  return result;
};
