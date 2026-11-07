import vm from 'node:vm';
import { FACE_TRACKER_HTML } from '../components/ar/faceTrackerHtml';

const match = FACE_TRACKER_HTML.match(/<script type="module">([\s\S]*?)<\/script>/);
if (!match) {
  console.error('no script');
  process.exit(1);
}
const body = match[1];
console.log('script bytes', body.length);
try {
  new vm.Script(body, { filename: 'face-tracker.js' });
  console.log('vm.Script ok');
} catch (error) {
  const err = error as Error;
  console.log('SCRIPT_ERROR');
  console.log(err.stack);
}
try {
  new Function(body);
  console.log('Function ok');
} catch (error) {
  const err = error as Error;
  console.log('FUNCTION_ERROR', err.message);
}
