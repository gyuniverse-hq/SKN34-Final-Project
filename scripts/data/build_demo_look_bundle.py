"""Builds lib/demoLookBundle.json: the six demo looks (videos + the catalog products they paint) shipped in the app.

The demo looks must open and paint with no backend answer (11-06: a dead dev server held them for 90 s).
Sources are the files the backend serves, so the bundle is the same data, not a substitute:
  - backend/api/seed/catalog.json (products; only the shades the looks use are kept)
  - backend/api/app/catalog_data/celebrity_videos.json and style_looks.json (video entries)
Slot product/shade ids are read from lib/demoLookAr.ts. Re-run after changing either:

    python scripts/data/build_demo_look_bundle.py
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SLOTS_TS = ROOT / "lib" / "demoLookAr.ts"
CATALOG = ROOT / "backend" / "api" / "seed" / "catalog.json"
CELEB = ROOT / "backend" / "api" / "app" / "catalog_data" / "celebrity_videos.json"
STYLE = ROOT / "backend" / "api" / "app" / "catalog_data" / "style_looks.json"
OUT = ROOT / "lib" / "demoLookBundle.json"


def read_slots() -> tuple[list[str], dict[str, set[str]]]:
    source = SLOTS_TS.read_text(encoding="utf-8")
    body = source[source.index("DEMO_LOOK_AR") :]
    video_ids = re.findall(r"^  '?([A-Za-z0-9_-]{11})'?: \[", body, re.M)
    shades: dict[str, set[str]] = {}
    pairs = re.findall(r"productId: '([^']+)', shadeId: '([^']+)'", body)
    for product_id, shade_id in pairs:
        shades.setdefault(product_id, set()).add(shade_id)
    return video_ids, shades


def main() -> None:
    video_ids, shades = read_slots()
    if len(video_ids) != 6:
        raise SystemExit(f"expected 6 demo looks in {SLOTS_TS.name}, found {video_ids}")
    products = json.loads(CATALOG.read_text(encoding="utf-8"))["products"]
    by_id = {p["id"]: p for p in products}
    bundled = []
    for product_id in sorted(shades):
        product = by_id.get(product_id)
        if product is None:
            raise SystemExit(f"{product_id} is not in {CATALOG}")
        kept = [s for s in product["shades"] if s["id"] in shades[product_id]]
        missing = shades[product_id] - {s["id"] for s in kept}
        if missing:
            raise SystemExit(f"{product_id} has no shade {sorted(missing)}")
        bundled.append({**product, "shades": kept})

    def pick(path: Path) -> list[dict]:
        items = json.loads(path.read_text(encoding="utf-8"))
        return [item for item in items if item["id"] in video_ids]

    celebrity = pick(CELEB)
    style = pick(STYLE)
    found = {item["id"] for item in celebrity + style}
    if found != set(video_ids):
        raise SystemExit(f"video entries missing: {sorted(set(video_ids) - found)}")
    OUT.write_text(
        json.dumps(
            {"products": bundled, "celebrityVideos": celebrity, "styleLooks": style},
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{OUT.relative_to(ROOT)}: {len(bundled)} products, {len(celebrity)} celebrity + {len(style)} style looks")


if __name__ == "__main__":
    main()
