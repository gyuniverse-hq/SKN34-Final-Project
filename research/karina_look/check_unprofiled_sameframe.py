"""Compare legacy and profile-aware material paths on the *same* WebGL frame.

The old and new pages are generated from the source before and after the
profile change. The test-only page injects the old material/finish functions
into the new renderer, pauses tracking, renders both paths at the same clock
instant and compares WebGL pixels in the browser. No face data leaves it.
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research/data/karina_look"
OUT = DATA / "unprofiled_regression"


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one marker: {old[:80]}")
    return text.replace(old, new)


def main() -> None:
    spec = importlib.util.spec_from_file_location("offline_render", ROOT / "research/lip_texture/render.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Missing existing offline render helper")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    old = (DATA / "page_before_profiles.html").read_text(encoding="utf-8")
    html = (DATA / "page_after_profiles.html").read_text(encoding="utf-8")
    start = old.index("    function material(zone) {")
    end = old.index("\n\n    return {", start)
    legacy = old[start:end].replace("function material(zone)", "function legacyMaterial(zone)")
    legacy = legacy.replace("function shadowFinish(zone)", "function legacyShadowFinish(zone)")
    html = replace_once(html, "    function material(zone) {",
                        legacy + "\n    function material(zone) {\n      if (window.__legacyProfilePath) return legacyMaterial(zone);")
    html = replace_once(html, "    function shadowFinish(zone) {",
                        "    function shadowFinish(zone) {\n      if (window.__legacyProfilePath) return legacyShadowFinish(zone);")
    html = replace_once(html, "      name: version,", """      name: version,
      researchPixels() {
        const pixels = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
        gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        return pixels;
      },""")
    html = replace_once(html, "  function processFrame(now) {", "  function processFrame(now) {\n    if (window.__researchPaused) return;")
    marker = "  // Prefer requestVideoFrameCallback (fires once per camera frame, AR_SPEC 6-1); else poll with rAF."
    test_hook = """  window.__researchCompare = () => {
    const t = performance.now(), W = video.videoWidth, H = video.videoHeight;
    Object.defineProperty(performance, 'now', { configurable: true, value: () => t });
    try {
      const draw = (legacy) => { window.__legacyProfilePath = legacy; renderer.render(W, H, false, false); return renderer.researchPixels(); };
      draw(true); draw(false);  // settle any existing face-layout work
      const a = draw(true), b = draw(false);
      let different = 0, max = 0;
      for (let i = 0; i < a.length; i += 4) {
        let pixelDiff = 0;
        for (let c = 0; c < 4; c++) pixelDiff = Math.max(pixelDiff, Math.abs(a[i + c] - b[i + c]));
        if (pixelDiff) different++;
        max = Math.max(max, pixelDiff);
      }
      const lip = makeup.lip;
      makeup.lip = Object.assign({}, lip, { applicationProfile: { material: { a1: 0.2, specular: 0.1 }, coverageMultiplier: 0.5 } });
      const changed = draw(false);
      makeup.lip = lip;
      let profiledPixels = 0;
      for (let i = 0; i < b.length; i += 4) {
        if (b[i] !== changed[i] || b[i + 1] !== changed[i + 1] || b[i + 2] !== changed[i + 2]) profiledPixels++;
      }
      return { width: W, height: H, differentPixels: different, maxChannelDifference: max, syntheticProfileChangedPixels: profiledPixels };
    } finally { delete performance.now; window.__legacyProfilePath = false; }
  };
"""
    html = replace_once(html, marker, test_hook + marker)
    makeup = json.loads((DATA / "app_makeup.json").read_text(encoding="utf-8"))["makeup"]
    if any(zone and zone.get("applicationProfile") for zone in makeup.values()):
        raise RuntimeError("Expected an unprofiled makeup state")
    if makeup.get("highlighter"):
        geometry = dict(makeup["highlighter"].get("geometry") or {})
        geometry["hlFace"] = "oval"
        makeup["highlighter"]["geometry"] = geometry
    face = (DATA / "whole_before/0005.png").read_bytes()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=helper.CHROME, headless=True,
                                     args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        try:
            ctx = browser.new_context(viewport={"width": 996, "height": 560}, ignore_https_errors=True)
            page = ctx.new_page()
            page.route("**/*", lambda route: route.abort())
            helper.routes(page, face, html)
            page.add_init_script(helper.FAKE_CAMERA)
            page.goto("https://localhost/")
            helper.wait_status(page, "tracking")
            page.evaluate("m => window.dispatchEvent(new MessageEvent('message', {data: JSON.stringify(m)}))",
                          {"type": "makeup", "stateSeq": 1, "makeup": makeup})
            time.sleep(12)
            page.evaluate("window.__researchPaused = true")
            result = page.evaluate("window.__researchCompare()")
            ctx.close()
        finally:
            browser.close()
    (OUT / "sameframe_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    if result["differentPixels"] != 0 or result["syntheticProfileChangedPixels"] <= 0:
        raise SystemExit("Same-frame regression or synthetic-profile test failed")


if __name__ == "__main__":
    main()
