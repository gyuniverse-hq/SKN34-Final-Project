import type { SkinWebRun } from '@/types/skin';

export function skinWebHtml(config: SkinWebRun, captureLabel: string) {
  const data = JSON.stringify(config).replaceAll('<', '\\u003c');
  const label = captureLabel.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#111}video{width:100%;height:100%;object-fit:cover;transform:scaleX(-1)}canvas{display:none}button{position:absolute;top:16px;right:16px;min-height:48px;min-width:96px;padding:12px 20px;border:0;border-radius:24px;background:#fff;color:#111;font:600 16px system-ui}button:disabled{opacity:.45}</style>
</head><body><video autoplay muted playsinline></video><canvas></canvas><button id="capture" type="button" disabled>${label}</button><script type="module">
const fail=()=>window.ReactNativeWebView?.postMessage(JSON.stringify({type:'error',code:'model'}));
window.addEventListener('error',fail);window.addEventListener('unhandledrejection',fail);
const config=${data};
import(config.assetsUrl+(config.mode==='server'?'capture.mjs':'runtime.mjs')).then(module=>module.boot(config)).catch(fail);
</script></body></html>`;
}
