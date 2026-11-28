import type { SkinWebRun } from '@/types/skin';

// The runtime enables the hidden capture control when its camera and face guide are ready.
export const skinWebCaptureScript = "document.getElementById('capture')?.click(); true;";

export function skinWebHtml(config: SkinWebRun) {
  const data = JSON.stringify(config).replaceAll('<', '\\u003c');
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#111}video{width:100%;height:100%;object-fit:cover;transform:scaleX(-1)}canvas{display:none}</style>
</head><body><video autoplay muted playsinline></video><canvas></canvas><button id="capture" type="button" hidden disabled></button><script type="module">
const fail=()=>window.ReactNativeWebView?.postMessage(JSON.stringify({type:'error',code:'model'}));
window.addEventListener('error',fail);window.addEventListener('unhandledrejection',fail);
const config=${data};
import(config.assetsUrl+'runtime.mjs').then(module=>module.boot(config)).catch(fail);
</script></body></html>`;
}
