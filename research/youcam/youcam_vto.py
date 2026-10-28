"""Perfect Corp YouCam Makeup VTO — research only (AR_SPEC 1-4, 1-13).

Uploads a still selfie, applies one zone, downloads the result. Never imported from
app/, components/, lib/, or server/. The live AR loop stays on-device.

    python research/youcam/compare_youcam.py --image <jpg> --hex '#DD5A59' --texture glossy

Key: YOUCAM_API_KEY in the repo .env (no EXPO_PUBLIC_). Consenting-team photos only.
Fitzpatrick, face-shape, lift, makeup-transfer result images are not used.
YouCam morphology (fullness / wrinkle smoothing) and foundation glow are 0 so the compare is
paint, not beautify. Results stay under research/data/youcam/ (git-ignored).
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = "https://yce-api-01.makeupar.com"
# Our MATERIALS names → YouCam lip texture enum.
TEXTURE = {
    "matte": "matte",
    "velvet": "matte",
    "cream": "satin",
    "satin": "satin",
    "sheer": "sheer",
    "glossy": "gloss",
    "gloss": "gloss",
    "shimmer": "shimmer",
    "metallic": "metallic",
    "holographic": "holographic",
}
GLOSSY = {"gloss", "holographic", "metallic", "sheer", "shimmer"}
SHIMMER = {"holographic", "metallic", "shimmer"}
# App Texture names → YouCam eye_shadow / eye_liner enum (only matte / shimmer / metallic).
SHADOW_TEXTURE = {
    "matte": "matte",
    "velvet": "matte",
    "cream": "matte",
    "satin": "matte",
    "sheer": "matte",
    "glossy": "metallic",
    "shimmer": "shimmer",
}
BLUSH_TEXTURE = {
    "matte": "matte",
    "velvet": "matte",
    "cream": "matte",
    "satin": "satin",
    "sheer": "matte",
    "glossy": "shimmer",
    "shimmer": "shimmer",
}
# Live shader numbers taken from YouCam fields. The app never calls YouCam.
SHADER_FROM_YOUCAM = {
    "sparkleLift": 0.5,  # eye_shadow shimmerIntensity 50 / 100
    "sparkleSpecShare": 0.09,
    "foundGlow": 0.0,
    "lipFullness": 0,
    "lipWrinkless": 0,
}


def _hex(hex_color: str) -> str:
    color = hex_color if hex_color.startswith("#") else "#" + hex_color
    return color.upper()


def intensity_to_shader(color_intensity: int) -> float:
    """YouCam colorIntensity 0..100 → app ZoneSetting.intensity 0..1."""
    return max(0.0, min(1.0, int(color_intensity) / 100.0))


def load_key() -> str:
    """YOUCAM_API_KEY from the environment, else the repo .env (never EXPO_PUBLIC_)."""
    key = os.environ.get("YOUCAM_API_KEY", "").strip()
    if key:
        return key
    env = ROOT / ".env"
    if not env.is_file():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("YOUCAM_API_KEY=") and not line.startswith("EXPO_PUBLIC_"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def lip_effect(hex_color: str, texture: str, intensity: int = 70) -> dict:
    """Lip paint only. No plump, no wrinkle-less (1-2, 1-3)."""
    tex = TEXTURE.get(texture.lower(), "satin")
    color = _hex(hex_color)
    pal = {"color": color, "texture": tex, "colorIntensity": int(intensity)}
    if tex in GLOSSY:
        pal["gloss"] = 70 if tex in ("gloss", "holographic", "metallic") else 40
    if tex in ("gloss", "sheer", "shimmer"):
        pal["transparencyIntensity"] = 40 if tex == "sheer" else 20
    if tex in SHIMMER:
        pal["shimmerColor"] = color
        pal["shimmerIntensity"] = 50
        pal["shimmerDensity"] = 50
        pal["shimmerSize"] = 40
    return {
        "category": "lip_color",
        "shape": {"name": "original"},
        "morphology": {"fullness": 0, "wrinkless": 0},
        "style": {"type": "full"},
        "palettes": [pal],
    }


def eye_shadow_effect(hex_color: str, texture: str, intensity: int = 70) -> dict:
    """One-color lid paint. Pattern 1color1. No skin-smooth (1-2, 1-3)."""
    tex = SHADOW_TEXTURE.get(texture.lower(), "matte")
    color = _hex(hex_color)
    pal: dict = {"color": color, "texture": tex, "colorIntensity": int(intensity)}
    if tex in ("shimmer", "metallic"):
        pal["shimmerColor"] = color
        pal["shimmerIntensity"] = 50 if tex == "shimmer" else 20
    if tex == "metallic":
        pal["metallicIntensity"] = 50
    return {
        "category": "eye_shadow",
        "pattern": {"name": "1color1"},
        "palettes": [pal],
    }


def blush_effect(hex_color: str, texture: str, intensity: int = 70) -> dict:
    """Cheek paint only. glowStrength 0 (does not brighten skin). Pattern 1color1."""
    tex = BLUSH_TEXTURE.get(texture.lower(), "matte")
    color = _hex(hex_color)
    pal: dict = {"color": color, "texture": tex, "colorIntensity": int(intensity), "glowStrength": 0}
    if tex == "shimmer":
        pal["shimmerColor"] = color
        pal["shimmerDensity"] = 50
    return {
        "category": "blush",
        "pattern": {"name": "1color1"},
        "palettes": [pal],
    }


def eye_liner_effect(hex_color: str, texture: str, intensity: int = 70) -> dict:
    """Liner color and gloss only. Wing shape stays LINER_LOOKS in the app."""
    tex = SHADOW_TEXTURE.get(texture.lower(), "matte")
    color = _hex(hex_color)
    pal: dict = {"color": color, "texture": tex, "colorIntensity": int(intensity)}
    if tex in ("shimmer", "metallic"):
        pal["shimmerColor"] = color
        pal["shimmerIntensity"] = 50 if tex == "shimmer" else 20
    if tex == "metallic":
        pal["metallicIntensity"] = 50
    return {
        "category": "eye_liner",
        "pattern": {"name": "2colors1"},
        "palettes": [pal],
    }


def eyebrows_effect(hex_color: str, intensity: int = 70) -> dict:
    """Brow color only. No curvature / thickness / definition (points stay)."""
    color = _hex(hex_color)
    return {
        "category": "eyebrows",
        "pattern": {"type": "color"},
        "palettes": [{"color": color, "colorIntensity": int(intensity), "texture": "matte"}],
    }


def foundation_effect(hex_color: str, intensity: int = 45) -> dict:
    """Thin tint. glowIntensity 0 so skin is not brightened."""
    color = _hex(hex_color)
    return {
        "category": "foundation",
        "palettes": [
            {
                "color": color,
                "colorIntensity": int(intensity),
                "glowIntensity": 0,
                "coverageIntensity": int(intensity),
            }
        ],
    }


def _req(method: str, url: str, key: str, data: bytes | None = None, content_type: str | None = None):
    headers = {"Authorization": f"Bearer {key}"}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            body = res.read()
            if not body:
                return {}
            if "json" in (res.headers.get("Content-Type") or ""):
                return json.loads(body.decode())
            return {"raw": body}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")
        raise SystemExit(f"YouCam {e.code} {url}: {err}") from e


def upload_file(path: Path, key: str) -> str:
    """File API: metadata → PUT bytes → file_id."""
    raw = path.read_bytes()
    ctype = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    meta = _req(
        "POST",
        f"{API}/s2s/v2.0/file",
        key,
        json.dumps({"files": [{"content_type": ctype, "file_name": path.name, "file_size": len(raw)}]}).encode(),
        "application/json",
    )
    files = (meta.get("data") or {}).get("files") or []
    if not files:
        raise SystemExit(f"YouCam file API: {meta}")
    item = files[0]
    put = item["requests"][0]
    put_req = urllib.request.Request(put["url"], data=raw, method=put.get("method") or "PUT")
    for hk, hv in (put.get("headers") or {}).items():
        put_req.add_header(hk, str(hv))
    with urllib.request.urlopen(put_req, timeout=120) as res:
        res.read()
    return item["file_id"]


def run_makeup(path: Path, key: str, effects: list, wait_s: float = 90) -> bytes:
    """Upload, start makeup-vto with the given effects, poll, return JPEG/PNG bytes."""
    file_id = upload_file(path, key)
    started = _req(
        "POST",
        f"{API}/s2s/v2.0/task/makeup-vto",
        key,
        json.dumps({"src_file_id": file_id, "effects": effects, "version": "1.0"}).encode(),
        "application/json",
    )
    task_id = (started.get("data") or {}).get("task_id")
    if not task_id:
        raise SystemExit(f"YouCam start: {started}")
    deadline = time.time() + wait_s
    while time.time() < deadline:
        time.sleep(2)
        st = _req("GET", f"{API}/s2s/v2.0/task/makeup-vto/{task_id}", key)
        data = st.get("data") or {}
        status = data.get("task_status")
        if status == "success":
            results = data.get("results") or {}
            url = results.get("url") or results.get("download_url")
            if isinstance(results, list) and results:
                url = results[0].get("download_url") or results[0].get("url")
            if not url:
                raise SystemExit(f"YouCam success without URL: {st}")
            with urllib.request.urlopen(url, timeout=60) as res:
                return res.read()
        if status == "error":
            raise SystemExit(f"YouCam task error: {data.get('failure_reason') or st}")
    raise SystemExit(f"YouCam timeout after {wait_s}s (task {task_id})")


def run_lip(path: Path, key: str, hex_color: str, texture: str, intensity: int = 70, wait_s: float = 90) -> bytes:
    """Upload, start makeup-vto, poll, return JPEG/PNG bytes."""
    return run_makeup(path, key, [lip_effect(hex_color, texture, intensity)], wait_s)


def run_liner(path: Path, key: str, hex_color: str, texture: str, intensity: int = 70, wait_s: float = 90) -> bytes:
    """Still-photo eyeliner only. Never imported from the Expo app."""
    return run_makeup(path, key, [eye_liner_effect(hex_color, texture, intensity)], wait_s)


if __name__ == "__main__":
    e = lip_effect("#dd5a59", "glossy")
    assert e["morphology"] == {"fullness": 0, "wrinkless": 0}
    assert e["style"]["type"] == "full"
    assert e["palettes"][0]["texture"] == "gloss"
    assert "gloss" in e["palettes"][0]
    m = lip_effect("B3202E", "matte")
    assert m["palettes"][0]["texture"] == "matte"
    assert "gloss" not in m["palettes"][0]
    sm = eye_shadow_effect("#8A5A44", "matte")
    assert sm["category"] == "eye_shadow"
    assert sm["pattern"]["name"] == "1color1"
    assert sm["palettes"][0]["texture"] == "matte"
    assert "shimmerColor" not in sm["palettes"][0]
    sh = eye_shadow_effect("8A5A44", "shimmer")
    assert sh["palettes"][0]["texture"] == "shimmer"
    assert sh["palettes"][0]["shimmerColor"] == "#8A5A44"
    gl = eye_shadow_effect("#8A5A44", "glossy")
    assert gl["palettes"][0]["texture"] == "metallic"
    assert gl["palettes"][0]["metallicIntensity"] == 50
    for e in (sm, sh, gl):
        assert e["category"] == "eye_shadow"
        assert "skinSmoothStrength" not in e
    assert intensity_to_shader(50) == 0.5
    assert SHADER_FROM_YOUCAM["sparkleLift"] == 0.5
    assert SHADER_FROM_YOUCAM["foundGlow"] == 0.0
    bl = blush_effect("#E8A090", "satin")
    assert bl["category"] == "blush"
    assert bl["palettes"][0]["glowStrength"] == 0
    assert blush_effect("#E8A090", "matte")["palettes"][0]["glowStrength"] == 0
    bls = blush_effect("E8A090", "shimmer")
    assert bls["palettes"][0]["texture"] == "shimmer"
    assert bls["palettes"][0]["shimmerDensity"] == 50
    ln = eye_liner_effect("#1A1A1A", "glossy")
    assert ln["category"] == "eye_liner"
    assert ln["palettes"][0]["texture"] == "metallic"
    assert ln["palettes"][0]["metallicIntensity"] == 50
    br = eyebrows_effect("#3D2B1F", 60)
    assert br["category"] == "eyebrows"
    assert br["pattern"]["type"] == "color"
    assert "curvature" not in br
    assert "thickness" not in br
    fd = foundation_effect("#C4A07A", 45)
    assert fd["palettes"][0]["glowIntensity"] == 0
    assert fd["palettes"][0]["coverageIntensity"] == 45
    print("youcam_vto self-check ok")
