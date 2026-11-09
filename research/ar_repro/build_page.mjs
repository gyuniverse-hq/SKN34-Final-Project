import fs from 'fs';
const [, , trackerTs, uvTs, out] = process.argv;
const s = fs.readFileSync(trackerTs, 'utf8');
const u = fs.readFileSync(uvTs, 'utf8');
function arr(name) {
  const key = 'export const ' + name + ': number[] = [';
  const a = u.indexOf(key);
  if (a < 0) throw new Error('missing ' + name);
  const b = u.indexOf(']', a + key.length);
  return JSON.parse('[' + u.slice(a + key.length, b) + ']');
}
const head = 'export const FACE_TRACKER_HTML = `';
const start = s.indexOf(head) + head.length;
const end = s.lastIndexOf('`;');
const body = s.slice(start, end);
const html = new Function('FACE_UV', 'FACE_TRIANGLES', 'FACE_MOUTH_TRIANGLES', 'MEDIAPIPE_VERSION', 'return `' + body + '`;')(
  arr('FACE_UV'), arr('FACE_TRIANGLES'), arr('FACE_MOUTH_TRIANGLES'), '1.1.1');
fs.writeFileSync(out, html);
console.log('page', out.split(/[\\/]/).pop(), html.length);
