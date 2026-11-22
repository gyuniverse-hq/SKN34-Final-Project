"""Compare the PR base and the fixed shader on one frozen offline tracking frame.

Input and output paths are explicit. Images stay local, and all network requests are blocked.
"""
import argparse
import copy
import importlib.util
import json
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
VIDEOS = ('ZAozXs-ZZik', '4QR0tre9yBI', 'kWI7_DkDjZ0', 'n5otfjJSSQc', 'fDqBPI1SaWY', 'e1gSkUdG6Bo')


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError(f'expected one marker: {before[:60]}')
    return text.replace(before, after, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', required=True, type=Path, help='existing research/data directory, read only')
    parser.add_argument('--baseline', required=True, type=Path, help='HTML page built from the PR base')
    parser.add_argument('--current', required=True, type=Path, help='HTML page built from this change')
    parser.add_argument('--output', required=True, type=Path, help='new local-only output directory')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('기존 비교 결과를 덮어쓰지 않습니다')
    data = args.data_root.resolve()
    look = data / 'look6'
    spec = importlib.util.spec_from_file_location('offline_render', ROOT / 'research/lip_texture/render.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.MP_WEB = data / 'mediapipe-web'
    helper.MODELS = data / 'models'
    code = "const fs=require('fs');const s=fs.readFileSync(process.argv[1],'utf8');const a=s.indexOf('  const PRECISION = [');const b=s.indexOf('  function createGLRenderer()');process.stdout.write(JSON.stringify(new Function('NL',s.slice(a,b)+';return MESH_FRAG;')(String.fromCharCode(10))));"
    previous_frag = json.loads(subprocess.check_output(['node', '-e', code, str(args.baseline.resolve())], cwd=ROOT))
    html = args.current.read_text(encoding='utf8')
    html = replace_once(html, '  function createGLRenderer() {',
                        '  const PREVIOUS_FRAG = ' + json.dumps(previous_frag) + ';\n  function createGLRenderer() {')
    html = replace_once(html, '      gl.linkProgram(p);',
                        "      ['aPos','aUv','aNormal','aLidM','aSeg'].forEach((name,i) => gl.bindAttribLocation(p,i,name));\n      gl.linkProgram(p);")
    html = replace_once(html, '    const bgPos = ',
                        "    const currentMesh = mesh, previousMesh = program(MESH_VERT, (xfadeOn ? '#define XFADE' + NL : '') + PREVIOUS_FRAG, MESH_UNIFORMS);\n    const bgPos = ")
    html = replace_once(html, '        gl.useProgram(mesh.p);',
                        '        mesh = window.__previousGlow ? previousMesh : currentMesh;\n        gl.useProgram(mesh.p);')
    html = replace_once(html, '      name: version,', '''      name: version,
      researchPixels() {
        const pixels = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
        gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        return pixels;
      },''')
    html = replace_once(html, '  function processFrame(now) {',
                        '  function processFrame(now) {\n    if (window.__glowPaused) return;')
    html = replace_once(html, '  // Prefer requestVideoFrameCallback', '''  window.__compareGlow = (state, natural) => {
    makeup = state; window.__glowPaused = true; TUNING.hlNatural = natural;
    const time = performance.now();
    Object.defineProperty(performance, 'now', {configurable:true, value:() => time});
    const draw = previous => {
      window.__previousGlow = previous;
      renderer.render(video.videoWidth, video.videoHeight, false, false);
      return renderer.researchPixels();
    };
    try {
      // Lip outline and thickness now use per-frame smoothing; settle it before pixel comparisons.
      for (let k=0;k<60;k++) { draw(true); draw(false); }
      const a=draw(true), b=draw(false); let pixels=0, max=0;
      for(let i=0;i<a.length;i+=4) {
        let delta=0; for(let c=0;c<4;c++) delta=Math.max(delta,Math.abs(a[i+c]-b[i+c]));
        if(delta) pixels++; max=Math.max(max,delta);
      }
      return {differentPixels:pixels,maxChannelDifference:max};
    } finally { delete performance.now; window.__previousGlow=false; }
  };
  window.__drawGlow = (state, previous) => {
    makeup = state; window.__glowPaused = true; TUNING.hlNatural = true; window.__previousGlow = previous;
    for(let i=0;i<6;i++) renderer.render(video.videoWidth, video.videoHeight, false, false);
  };
  // Prefer requestVideoFrameCallback''')
    states = {name: json.loads((look / name / 'app_makeup.json').read_text(encoding='utf8'))['makeup'] for name in VIDEOS}
    shown = json.loads((look / 'e1gSkUdG6Bo/shown_makeup.json').read_text(encoding='utf8'))['makeup']
    if shown.get('highlighter', {}).get('applicationProfile', {}).get('glow', 0) <= 0:
        raise ValueError('positive-control look has no glow')
    args.output.mkdir(parents=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=helper.CHROME, headless=True,
                                             args=['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
        try:
            page = browser.new_page(viewport={'width': 996, 'height': 560})
            page.route('**/*', lambda route: route.abort())
            helper.routes(page, (look / 'manual/e1gSkUdG6Bo_0001_bare.png').read_bytes(), html)
            page.add_init_script(helper.FAKE_CAMERA)
            page.goto('https://localhost/')
            helper.wait_status(page, 'tracking')
            time.sleep(8)
            plain = {name: page.evaluate('s => window.__compareGlow(s, true)', state) for name, state in states.items()}
            enabled = page.evaluate('s => window.__compareGlow(s, true)', shown)
            disabled_state = copy.deepcopy(shown)
            disabled_state['highlighter']['applicationProfile']['glow'] = 0
            disabled = page.evaluate('s => window.__compareGlow(s, true)', disabled_state)
            legacy = page.evaluate('s => window.__compareGlow(s, false)', shown)
            for previous, name in [(True, 'before.png'), (False, 'after.png')]:
                page.evaluate('([s,p]) => window.__drawGlow(s,p)', [shown, previous])
                helper.shot(page, args.output / name, n=1)
            result = {'withoutLookGlow': plain, 'lookNatural': enabled, 'lookZeroGlow': disabled, 'lookLegacy': legacy}
            (args.output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
            print(json.dumps(result), flush=True)
            if any(row['differentPixels'] for row in plain.values()):
                raise RuntimeError('룩 물광이 없는 상태가 변경되었습니다')
            if not enabled['differentPixels']:
                raise RuntimeError('자연광에서 룩 물광이 작동하지 않습니다')
            if disabled['differentPixels']:
                raise RuntimeError('물광 0인 룩이 변경되었습니다')
            if legacy['differentPixels']:
                raise RuntimeError('기존 하이라이터 경로가 변경되었습니다')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
