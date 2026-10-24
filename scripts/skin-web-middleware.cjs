// Development camera assets; skin model assets are available only in explicit on-device mode.
const { createReadStream, readFileSync, existsSync } = require('node:fs');
const { resolve, dirname, extname } = require('node:path');

module.exports = function skinWebMiddleware(root) {
  const assets = resolve(root, 'modules/skin-analysis/android/src/main/assets/skin');
  const web = resolve(root, 'modules/skin-analysis/web');
  const onDevice = process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE === 'on-device';
  const ort = onDevice ? dirname(require.resolve('onnxruntime-web/wasm')) : null;
  const files = new Map([
    ['runtime.mjs', resolve(web, 'runtime.mjs')], ['preprocessing.mjs', resolve(web, 'preprocessing.mjs')],
    ['gate.mjs', resolve(web, 'gate.mjs')], ['opencv.js', require.resolve('@techstark/opencv-js')],
    ['jpeg.mjs', resolve(web, 'jpeg.mjs')],
    ['jpeg.js', require.resolve('@cornerstonejs/codec-libjpeg-turbo-8bit/wasmjs')],
    ['libjpegturbowasm.wasm', require.resolve('@cornerstonejs/codec-libjpeg-turbo-8bit/wasm')],
    ...(onDevice ? ['ort.wasm.min.mjs', 'ort-wasm-simd-threaded.mjs', 'ort-wasm-simd-threaded.wasm'].map(name => [name, resolve(ort, name)]) : []),
  ]);
  const cameraFiles = new Map([['capture.mjs', resolve(web, 'capture.mjs')], ['gate.mjs', resolve(web, 'gate.mjs')]]);
  let manifest;
  return (req, res, next) => {
    const url = new URL(req.url, 'http://localhost');
    if (!url.pathname.startsWith('/skin-runtime/')) return next();
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405); res.end(); return; }
    try {
      const camera = cameraFiles.get(url.pathname.slice('/skin-runtime/'.length));
      if (camera) {
        res.setHeader('Content-Type', 'text/javascript'); res.setHeader('Cache-Control', 'no-cache');
        if (req.method === 'HEAD') res.end();
        else createReadStream(camera).on('error', () => res.destroy()).pipe(res);
        return;
      }
      if (!onDevice) { res.writeHead(404); res.end(); return; }
      if (!manifest) {
        const candidate = JSON.parse(readFileSync(resolve(assets, 'manifest.json'), 'utf8'));
        if (!/^[a-f0-9]{64}$/.test(candidate.bundleVersion) || !candidate.assets ||
          Object.entries(candidate.assets).some(([name, hash]) =>
            !/^[a-zA-Z0-9_-]+\.(onnx|png|f32|xml|json)$/.test(name) || !/^[a-f0-9]{64}$/.test(hash))) throw new Error('Invalid asset manifest');
        manifest = candidate;
      }
      const name = url.pathname.slice('/skin-runtime/'.length);
      if (name === 'manifest.json') {
        res.setHeader('Cache-Control', 'no-store'); res.setHeader('Content-Type', 'application/json');
        res.end(req.method === 'HEAD' ? undefined : JSON.stringify(manifest)); return;
      }
      const prefix = `${manifest.bundleVersion}/`;
      const asset = name.startsWith(prefix) ? name.slice(prefix.length) : null;
      const file = asset && Object.hasOwn(manifest.assets, asset) ? resolve(assets, asset) : files.get(name);
      if (!file || !existsSync(file)) { res.writeHead(404); res.end(); return; }
      const type = { '.js': 'text/javascript', '.mjs': 'text/javascript', '.wasm': 'application/wasm',
        '.json': 'application/json', '.png': 'image/png' }[extname(file)] || 'application/octet-stream';
      res.setHeader('Content-Type', type);
      res.setHeader('Cache-Control', asset ? 'public, max-age=31536000, immutable' : 'no-cache');
      if (req.method === 'HEAD') { res.end(); return; }
      createReadStream(file).on('error', () => res.destroy()).pipe(res);
    } catch { res.writeHead(503); res.end('Skin assets missing. Run npm run skin:prepare.'); }
  };
};
