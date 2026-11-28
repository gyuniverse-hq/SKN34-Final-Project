"""Independent read-only price/identity cross-check of the real PG dialogue output."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET
import sys

import httpx

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/g8/parent"
label = sys.argv[1] if len(sys.argv) > 1 else "settled"
props = ET.parse(OUT / f"common-parent-product-contract-live-pg-{label}.xml").iter("property")
dialogue = json.loads(next(p.get("value") for p in props if p.get("name") == "live_product_contract"))
response = httpx.get("http://127.0.0.1:19834/api/products", params={"category": "skincare"}, timeout=40)
response.raise_for_status()
rows = {p["id"]: p for p in response.json()["products"]}
checks = []
for turn in dialogue["turns"]:
    for task in turn["parent"]["tasks"]:
        if task["goal"] != "product":
            continue
        budget = task["productContext"]["filters"]["maxPriceKRW"]
        if task["displayResult"] is None:
            checks.append({"question": turn["question"], "taskId": task["taskId"],
                           "status": task["status"], "preservation": "FAIL: missing unchanged task result"})
            continue
        ids = [p["id"] for p in task["displayResult"]["products"]]
        items = [{"id": pid, "name": rows[pid]["name"], "priceKRW": rows[pid]["priceKRW"]} for pid in ids]
        assert all(p["priceKRW"] > 0 and (budget is None or p["priceKRW"] <= budget) for p in items)
        checks.append({"question": turn["question"], "taskId": task["taskId"],
                       "kind": task["productRequirement"]["kind"], "maxPriceKRW": budget,
                       "items": items, "identityAndPrice": "PASS"})
record = {"at": datetime.now(timezone.utc).isoformat(), "catalogHttp": "real localhost:19834",
          "responseSha256": hashlib.sha256(response.content).hexdigest(), "rowCount": len(rows),
          "catalogBuildSha": "not exposed by endpoint", "checks": checks,
          "qualification": "post-dialogue snapshot; product-name evidence, not efficacy or live seller pricing",
          "dialogue": dialogue}
(OUT / f"common-parent-product-contract-live-dialogue-{label}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print("Verified", len(checks), "task result sets against", len(rows), "live Catalog rows")
