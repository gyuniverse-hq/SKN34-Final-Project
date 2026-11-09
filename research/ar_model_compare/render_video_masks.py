"""Render external video masks through the app shader in a research-only browser.

The masks and source frames must be produced by video_masks.py with the same
video hash and frame indices. Output stays in research/data by default. This
does not modify the app, measure real-time performance, or use a GPU server.
"""
import argparse
import base64
import csv
import hashlib
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research/lip_texture"))
from render import CHROME, FAKE_CAMERA, page_html, routes, send_makeup, wait_status  # noqa: E402


def inject(html):
    old = "'float outlineAt(vec2 s) { return outline2(s).r; }',"
    new = ("'uniform sampler2D uCompareMask; uniform float uCompareOn;',\n"
           "    'float outlineAt(vec2 s) { return mix(outline2(s).r, texture2D(uCompareMask, s).r, uCompareOn); }',")
    init = "    const videoTex = gl.createTexture();"
    init_new = """    const compareTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE10); gl.bindTexture(gl.TEXTURE_2D, compareTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0,0,0,255]));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.activeTexture(gl.TEXTURE0);
    const videoTex = gl.createTexture();"""
    render = "        gl.useProgram(mesh.p);"
    render_new = """        gl.useProgram(mesh.p);
        gl.activeTexture(gl.TEXTURE10); gl.bindTexture(gl.TEXTURE_2D, compareTex);
        if (window.__comparisonMask) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, window.__comparisonMask);
        gl.uniform1i(gl.getUniformLocation(mesh.p, 'uCompareMask'), 10);
        gl.uniform1f(gl.getUniformLocation(mesh.p, 'uCompareOn'), window.__comparisonMask ? 1 : 0);
        gl.activeTexture(gl.TEXTURE0);"""
    for before, after in ((old, new), (init, init_new), (render, render_new)):
        if html.count(before) != 1:
            raise ValueError(f"Expected one renderer marker: {before}")
        html = html.replace(before, after)
    return html


def data_url(data):
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def png(image):
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Cannot encode frame")
    return buf.tobytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--masks", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--settle", type=float, default=0.5)
    args = ap.parse_args()
    if args.limit < 0 or args.settle <= 0:
        ap.error("invalid limit or settle time")
    metadata = json.loads((args.masks / "metadata.json").read_text(encoding="utf8"))
    if hashlib.sha256(args.video.read_bytes()).hexdigest() != metadata["video_sha256"]:
        raise ValueError("Mask video hash does not match source video")
    with (args.masks / "frames.csv").open(encoding="utf8", newline="") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        raise ValueError("Empty frame manifest")
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise ValueError("Cannot open video")
    args.output.mkdir(parents=True, exist_ok=True)
    width, height = int(metadata["width"]), int(metadata["height"])
    first_idx = int(rows[0]["frame"])
    cap.set(cv2.CAP_PROP_POS_FRAMES, first_idx)
    ok, frame = cap.read()
    if not ok:
        raise ValueError("Cannot decode first frame")
    frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    html = inject(page_html())
    outputs = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, headless=True,
            args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--autoplay-policy=no-user-gesture-required"])
        ctx = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1, ignore_https_errors=True)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(FAKE_CAMERA.replace("const __img = new Image();", "const __img = window.__compareImage = new Image();"))
        routes(page, png(frame), html)
        page.goto("https://localhost/")
        wait_status(page, "tracking")
        send_makeup(page, {"hex": "#B3202E", "texture": "satin", "intensity": 0.6})
        time.sleep(2)
        for row in rows:
            index = int(row["frame"])
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = cap.read()
            if not ok:
                raise ValueError(f"Cannot decode frame {index}")
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            mask_path = args.masks / "masks" / row["mask"]
            mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
            if mask is None or mask.shape != (height, width):
                raise ValueError(f"Invalid mask {mask_path}")
            frame_uri = data_url(png(frame))
            mask_uri = data_url(png(mask))
            page.evaluate("""async ([frame, mask]) => {
              window.__compareImage.src = frame; await window.__compareImage.decode();
              const m = new Image(); m.src = mask; await m.decode(); window.__comparisonMask = m;
            }""", [frame_uri, mask_uri])
            time.sleep(args.settle)
            output_path = args.output / f"{index:06d}.png"
            page.locator("#canvas").screenshot(path=str(output_path))
            outputs.append({"frame": index, "time_seconds": row["time_seconds"], "image": output_path.name})
            print(f"rendered frame {index}", flush=True)
        if errors:
            raise RuntimeError("Browser errors: " + "; ".join(errors))
        ctx.close()
        browser.close()
    cap.release()
    (args.output / "render_metadata.json").write_text(json.dumps({"model": metadata["model"],
        "video_sha256": metadata["video_sha256"], "colour": "#B3202E", "texture": "satin", "intensity": 0.6,
        "frames": outputs, "note": "Research-only app shader, static frame captures at sampled times; mesh and form remain MediaPipe, selected segmentation mask replaces outline red channel; not a real-time measurement."}, indent=2) + "\n", encoding="utf8")


if __name__ == "__main__":
    main()
