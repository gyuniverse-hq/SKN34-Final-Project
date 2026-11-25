"""Keep known color provenance consistent in exact serving/dev/demo shade identities."""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIELDS = ("measureMethod", "colorSource", "colorConfidence")


def _shades(path):
    data = json.loads((ROOT / path).read_text(encoding="utf-8"))
    return {(p["id"], s["id"]): s for p in data["products"] for s in p["shades"]}


def test_known_seed_shade_provenance_matches_exact_derived_catalog_shades():
    seed = _shades("backend/api/seed/catalog.json")
    for path in ("lib/devCatalog/oyCatalog.json", "lib/demoLookBundle.json"):
        checked = 0
        for key, shade in _shades(path).items():
            source = seed.get(key)
            if source is None or (shade["name"], shade["hex"].upper()) != (
                source["name"],
                source["hex"].upper(),
            ):
                continue
            if not all(source.get(field) is not None for field in FIELDS):
                continue
            assert shade.get("measureMethod") == source["measureMethod"], (path, key)
            assert shade.get("colorSource") == source["colorSource"], (path, key)
            assert shade.get("colorConfidence") is not None, (path, key)
            assert math.isclose(
                shade["colorConfidence"], source["colorConfidence"], abs_tol=1e-6
            ), (path, key)
            checked += 1
        assert checked > 0, path
