"""Compile the actual renderer's four GLSL variants locally, without sending image data."""
from __future__ import annotations

import importlib.util
import subprocess

from playwright.sync_api import sync_playwright

from blend_modes import DATA, ROOT


def main():
    output = DATA / 'e1gSkUdG6Bo/shader_check.html'
    subprocess.run(['node', 'research/ar_repro/glsl2.mjs', 'components/ar/faceTrackerHtml.ts', str(output)], cwd=ROOT, check=True)
    spec = importlib.util.spec_from_file_location('offline', ROOT / 'research/lip_texture/render.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=helper.CHROME, headless=True, args=['--enable-unsafe-swiftshader'])
        try:
            page = browser.new_page()
            page.route('https://**/*', lambda route: route.abort())
            page.goto(output.as_uri(), wait_until='commit')
            page.wait_for_function("document.getElementById('o').textContent.startsWith('RESULT')", timeout=120000)
            result = page.locator('#o').inner_text()
            print(result, flush=True)
            (output.parent / 'shader_check.txt').write_text(result, encoding='utf8')
            if result.count('vs=true fs=true link=true') != 4:
                raise RuntimeError('A WebGL shader variant failed')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
