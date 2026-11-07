const fs = require('fs');
const s = fs.readFileSync('components/ar/faceTrackerHtml.ts', 'utf8');
const a = s.indexOf('<script type="module">');
const b = s.lastIndexOf('</script>');
if (a < 0 || b < 0) {
  console.error('script tags not found', a, b);
  process.exit(1);
}
let body = s.slice(a + '<script type="module">'.length, b);
body = body
  .replace(/\$\{MEDIAPIPE_VERSION\}/g, '"1.1.1"')
  .replace(/\$\{JSON\.stringify\(FACE_UV\)\}/g, '[]')
  .replace(/\$\{JSON\.stringify\(FACE_TRIANGLES\)\}/g, '[]')
  .replace(/\$\{JSON\.stringify\(FACE_MOUTH_TRIANGLES\)\}/g, '[]');
fs.writeFileSync('.cursor/jaw-script-check.js', body);
console.log('bytes', body.length);
const vm = require('vm');
try {
  new vm.Script(body);
  console.log('vm.Script ok');
} catch (e) {
  console.log('SCRIPT_ERROR');
  console.log(e && e.stack ? e.stack.split('\n').slice(0, 8).join('\n') : e);
}
