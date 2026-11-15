"""Compare saved pre-task shader/canvas and current renderer on one identical tracked frame.

Local-only diagnostic. Reads ignored snapshots and writes numeric results there.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import time

from playwright.sync_api import sync_playwright

from blend_modes import DATA, ROOT


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Expected one marker: {old[:80]}')
    return text.replace(old, new, 1)


def main():
    spec = importlib.util.spec_from_file_location('offline', ROOT / 'research/lip_texture/render.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    folder = DATA / 'e1gSkUdG6Bo'
    old = (folder / 'source_prev/page.html').read_text(encoding='utf8')
    html = (DATA / 'page.html').read_text(encoding='utf8')
    # The generated page contains ordinary JS rather than TS template escapes.
    code = "const fs=require('fs');const s=fs.readFileSync(process.argv[1],'utf8');const a=s.indexOf('  const PRECISION = [');const b=s.indexOf('  function createGLRenderer()');process.stdout.write(JSON.stringify(new Function('NL',s.slice(a,b)+';return MESH_FRAG;')(String.fromCharCode(10))));"
    old_frag = json.loads(subprocess.check_output(['node', '-e', code, str(folder / 'source_prev/page.html')], cwd=ROOT))
    a = old.index('  function drawEyes(')
    b = old.index('  // ── Blush from the face points:', a)
    legacy_draw = old[a:b].replace('function drawEyes(', 'function legacyDrawEyes(', 1)
    html = once(html, '  function drawEyes(W, H, liner, mascara, shadow, browPaint) {',
                legacy_draw + '  function drawEyes(W, H, liner, mascara, shadow, browPaint) {\n    if (window.__legacyLook) return legacyDrawEyes(W, H, liner, mascara, shadow, browPaint);')
    html = once(html, '  function createGLRenderer() {', '  const PREVIOUS_FRAG = ' + json.dumps(old_frag) + ';\n  function createGLRenderer() {')
    html = once(html, '      gl.linkProgram(p);', "      ['aPos','aUv','aNormal','aLidM','aSeg'].forEach((name,i) => gl.bindAttribLocation(p,i,name));\n      gl.linkProgram(p);")
    html = once(html, '    const bgPos = ', "    const currentMesh = mesh, previousMesh = program(MESH_VERT, (xfadeOn ? '#define XFADE' + NL : '') + PREVIOUS_FRAG, MESH_UNIFORMS);\n    const bgPos = ")
    html = once(html, '        gl.useProgram(mesh.p);', '        mesh = window.__legacyLook ? previousMesh : currentMesh;\n        gl.useProgram(mesh.p);')
    html = once(html, '      name: version,', '''      name: version,
      readResearchPixels() {
        const pixels = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
        gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        return pixels;
      },''')
    html = once(html, '  function processFrame(now) {', '  function processFrame(now) {\n    if (window.__researchPaused) return;')
    marker = '  // Prefer requestVideoFrameCallback'
    html = once(html, marker, '''  window.__compareLook = (state, adaptOnly = false) => {
    makeup = state; window.__researchPaused = true;
    const flat = JSON.parse(JSON.stringify(state));
    for (const zone of Object.values(flat)) if (zone && zone.applicationProfile) zone.applicationProfile.skinAdapt = 0;
    const time = performance.now();
    Object.defineProperty(performance, 'now', {configurable:true, value:() => time});
    const draw = (previous) => {
      makeup = adaptOnly && previous ? flat : state;
      window.__legacyLook = adaptOnly ? false : previous;
      renderer.render(video.videoWidth, video.videoHeight, false, false);
      return renderer.readResearchPixels();
    };
    try {
      for (let k=0;k<6;k++) { draw(true); draw(false); }
      const a=draw(true), b=draw(false);
      let pixels=0, max=0;
      for (let i=0;i<a.length;i+=4) {
        let delta=0;
        for (let c=0;c<4;c++) delta=Math.max(delta,Math.abs(a[i+c]-b[i+c]));
        if(delta) pixels++; max=Math.max(max,delta);
      }
      return {differentPixels:pixels,maxChannelDifference:max};
    } finally { delete performance.now; window.__legacyLook=false; }
  };
''' + marker)
    html = once(html, '  const TUNING = {', '  const TUNING = {\n    // Original defaults retained; jobs are allowed to settle before comparison.')
    states = {}
    for video in ('ZAozXs-ZZik', '4QR0tre9yBI', 'kWI7_DkDjZ0', 'n5otfjJSSQc', 'fDqBPI1SaWY', 'e1gSkUdG6Bo'):
        states[video] = json.loads((DATA / video / 'app_makeup.json').read_text(encoding='utf8'))['makeup']
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=helper.CHROME, headless=True, args=['--enable-unsafe-swiftshader'])
        try:
            page = browser.new_page(viewport={'width': 996, 'height': 560})
            page.route('**/*', lambda route: route.abort())
            helper.routes(page, (DATA / 'manual/e1gSkUdG6Bo_0001_bare.png').read_bytes(), html)
            page.add_init_script(helper.FAKE_CAMERA)
            page.goto('https://localhost/')
            helper.wait_status(page, 'tracking')
            time.sleep(8)
            result = {video: page.evaluate('state => window.__compareLook(state)', state) for video, state in states.items()}
            shown = json.loads((folder / 'shown_makeup.json').read_text(encoding='utf8'))['makeup']
            positive = page.evaluate('state => window.__compareLook(state)', shown)
            adapt_front = page.evaluate('state => window.__compareLook(state, true)', shown)
            page.close()
            warm = browser.new_page(viewport={'width': 996, 'height': 560})
            warm.route('**/*', lambda route: route.abort())
            helper.routes(warm, (DATA / 'manual/ZAozXs-ZZik_0_bare.png').read_bytes(), html)
            warm.add_init_script(helper.FAKE_CAMERA)
            warm.goto('https://localhost/')
            helper.wait_status(warm, 'tracking')
            time.sleep(8)
            adapt_warm = warm.evaluate('state => window.__compareLook(state, true)', shown)
            report = {'unprofiled': result, 'enabledLook': positive, 'skinAdapt': {'front': adapt_front, 'warm': adapt_warm}}
            (folder / 'legacy_regression.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            print(json.dumps(result), flush=True)
            print('Enabled-look positive control:', json.dumps(positive), flush=True)
            print('Skin adaptation:', json.dumps(report['skinAdapt']), flush=True)
            if any(row['differentPixels'] for row in result.values()):
                raise RuntimeError('Legacy render changed; inspect numeric results')
            if not positive['differentPixels']:
                raise RuntimeError('Enabled-look positive control was empty')
            if adapt_front['differentPixels'] or not adapt_warm['differentPixels']:
                raise RuntimeError('Skin adaptation must leave the reference alone and change warm skin')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
