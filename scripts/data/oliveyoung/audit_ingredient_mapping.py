"""Finalize a review report; optionally replay an exact CSV snapshot without modifying seeds.

Run with backend/api's existing environment. Input candidate rows must be SELECT observations,
not an approval. Reproduction is independent of human ingredient review.
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend/api"))

from app.jobs.build_oy_catalog_from_csv import _products_from_dir
from app.repositories.ingredient_repository import catalog_fingerprint, fingerprint
from app.schemas.catalog import CatalogBundle
from app.services import oy_catalog

GENERATORS = [
    "backend/api/app/jobs/build_oy_catalog_from_csv.py",
    "backend/api/app/services/oy_catalog.py",
    "backend/api/app/schemas/oy_catalog.py",
]


def generator_version():
    return fingerprint({p: (ROOT / p).read_text(encoding="utf-8") for p in GENERATORS})


def replay_snapshot(folder, seed, client, manifest=None):
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.glob("*.csv"))
    }
    inputs = _products_from_dir(folder)  # Original CSV order and original filtering.
    owners = {id(s): p.goods_no for p in inputs for s in p.shades}
    traced = []
    original = oy_catalog._shade_id

    def trace(shade, used):
        sid = original(shade, used)
        goods = owners[id(shade)]
        traced.append(
            {
                "productId": ("oy-" + goods.lower())[:64],
                "shadeId": sid,
                "goodsNo": goods,
                "optionId": shade.option_id,
            }
        )
        return sid

    with patch.object(oy_catalog, "_shade_id", trace):
        built = oy_catalog.build_oy_catalog(inputs)
    generated = CatalogBundle(products=built.products).model_dump(
        mode="json", by_alias=True
    )
    generated_client = json.loads(json.dumps(generated))
    urls = {("oy-" + r.goods_no.lower())[:64]: r.product_url for r in inputs}
    for product in generated_client["products"]:
        if urls.get(product["id"]):
            product["sourceUrl"] = urls[product["id"]]
        for shade in product["shades"]:
            shade["measureMethod"] = "estimated"
    anchored = bool(
        manifest
        and manifest.get("inputHashes") == hashes
        and manifest.get("generatorVersion") == generator_version()
        and manifest.get("catalogFingerprint") == fingerprint(seed)
        and manifest.get("clientFingerprint") == fingerprint(client)
        and manifest.get("generationRecordId")
        and manifest.get("command")
    )
    return {
        "provenanceMatches": anchored,
        "matches": generated == seed and generated_client == client,
        "seedMatches": generated == seed,
        "clientMatches": generated_client == client,
        "seedOutputFingerprint": fingerprint(generated),
        "clientOutputFingerprint": fingerprint(generated_client),
        "inputHashes": hashes,
        "sourceFingerprint": fingerprint(hashes),
        "trace": traced,
    }


def finalize_report(observation, seed, client, snapshot=None, manifest=None):
    if "rawOptions" in observation:
        groups = {}
        for option_id, goods, code in observation["rawOptions"]:
            slug = (
                re.sub(r"[^a-z0-9]+", "-", (code or option_id).lower()).strip("-")
                or "shade"
            )
            groups.setdefault(("oy-" + goods.lower(), slug[:60]), []).append(option_id)
        input_rows = []
        for p in seed["products"]:
            for shade in p["shades"]:
                options = set(groups.get((p["id"], shade["id"]), []))
                for (pid, base), group in groups.items():
                    suffix = shade["id"][len(base[:56]) + 1 :]
                    if (
                        pid == p["id"]
                        and len(group) > 1
                        and shade["id"].startswith(base[:56] + "-")
                        and suffix.isdigit()
                        and int(suffix) >= 2
                    ):
                        options.update(group)
                input_rows.append(
                    [
                        p["id"],
                        shade["id"],
                        p["id"].removeprefix("oy-").upper(),
                        sorted(options),
                    ]
                )
        observation = {**observation, "inputRows": input_rows}
    goods_by_product = {}
    for _, goods, _ in observation.get("rawOptions", []):
        goods_by_product.setdefault("oy-" + goods.lower(), set()).add(goods)
    version = generator_version()
    source = fingerprint(observation["inputRows"])
    replay = replay_snapshot(snapshot, seed, client, manifest) if snapshot else None
    traced = (
        {(r["productId"], r["shadeId"]): r for r in replay["trace"]} if replay else {}
    )
    candidates = {(r[0], r[1]): r[3] for r in observation["inputRows"]}
    records = []
    for product in seed["products"]:
        cat_hash = catalog_fingerprint(
            product["id"],
            product["makeupZone"],
            product["texture"],
            [(s["id"], s["name"], s["hex"]) for s in product["shades"]],
        )
        for shade in product["shades"]:
            key = (product["id"], shade["id"])
            options = candidates.get(key, [])
            trace = traced.get(key)
            status = (
                "candidate"
                if len(options) == 1
                else "ambiguous"
                if options
                else "unmapped"
            )
            option = options[0] if len(options) == 1 else None
            if replay:
                status = (
                    ("reproduced" if replay["provenanceMatches"] else "candidate")
                    if replay["matches"] and trace
                    else "mismatch"
                )
                option = trace["optionId"] if trace else None
            records.append(
                {
                    "productId": product["id"],
                    "shadeId": shade["id"],
                    "goodsNo": trace["goodsNo"]
                    if trace
                    else next(iter(goods_by_product[product["id"]]))
                    if len(goods_by_product.get(product["id"], set())) == 1
                    else None,
                    "optionId": option,
                    "candidateOptionIds": options,
                    "mappingStatus": status,
                    "mappingMethod": (
                        "generator_replay"
                        if replay["provenanceMatches"]
                        else "unanchored_replay"
                    )
                    if replay
                    else "current_db_slug_candidate_only",
                    "sourceFingerprint": replay["sourceFingerprint"]
                    if replay
                    else source,
                    "generationRecordId": manifest.get("generationRecordId")
                    if manifest
                    else None,
                    "generatorVersion": version,
                    "catalogFingerprint": cat_hash,
                    "reviewStatus": "unreviewed",
                    "ingredientCoverage": "unknown",
                    "normalizationStatus": "unverified",
                }
            )
    return {
        **observation,
        "schemaVersion": 1,
        "exactSnapshotAvailable": bool(replay and replay["provenanceMatches"]),
        "snapshotProvided": snapshot is not None,
        "catalogFingerprint": fingerprint(seed),
        "clientFingerprint": fingerprint(client),
        "generatorVersion": version,
        "records": records,
        "summary": dict(Counter(r["mappingStatus"] for r in records)),
        "replay": {k: v for k, v in replay.items() if k != "trace"} if replay else None,
        "ingredientReviewApproved": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--snapshot-manifest", type=Path)
    args = parser.parse_args()
    observation = json.loads(args.report.read_text(encoding="utf-8"))
    seed = json.loads(
        (ROOT / "backend/api/seed/catalog.json").read_text(encoding="utf-8")
    )
    client = json.loads(
        (ROOT / "lib/devCatalog/oyCatalog.json").read_text(encoding="utf-8")
    )
    manifest = (
        json.loads(args.snapshot_manifest.read_text(encoding="utf-8"))
        if args.snapshot_manifest
        else None
    )
    result = finalize_report(observation, seed, client, args.snapshot, manifest)
    args.report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main()
