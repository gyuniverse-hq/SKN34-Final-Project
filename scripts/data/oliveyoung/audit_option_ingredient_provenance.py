"""Read-only, exhaustive option provenance audit. No automatic data repair/approval.

Run with G_AUDIT_DSN pointing at an isolated restored PostgreSQL database.
Counts describe detectable risks, not a manufacturer's confirmed formulation.
"""

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).parent / "collectors"))
from oliveyoung_erd_v30 import ingredient_observation

AMOUNT = re.compile(r"\d[\d.,]*\s*(?:%|ppm|ppb|iu)\b|\d[\d.,]*\s*%", re.I)


def classify(observation, legacy):
    entries = json.loads(observation["entries"])
    by_norm = defaultdict(list)
    for entry in entries:
        by_norm[entry["ingredient_norm"]].append(entry)
    amount_risk = False
    for name, norm, _ in legacy:
        amounts = AMOUNT.findall(name or "")
        if amounts and (not by_norm[norm] or all(
            [re.sub(r"\s+", "", x).lower() for x in amounts]
            != [re.sub(r"\s+", "", x).lower() for x in AMOUNT.findall(e["name"])]
            for e in by_norm[norm]
        )):
            amount_risk = True
    old = Counter(norm for _, norm, _ in legacy)
    # Repetition across different shades/components is not an occurrence lost
    # within a single list. Count repetitions within each preserved source block.
    repeated_loss = any(
        max(Counter(e["block"] for e in rows).values(), default=0) > old[norm] and old[norm]
        for norm, rows in by_norm.items()
    )
    # A union of multiple disclosed blocks in a legacy option is observable;
    # whether those blocks belong in the marketed option still requires human review.
    exclusive = {norm: {e["block"] for e in rows} for norm, rows in by_norm.items()}
    linked_blocks = set().union(*(blocks for norm, blocks in exclusive.items()
                                 if old[norm] and len(blocks) == 1))
    component_risk = bool(legacy and observation["ownership_status"] == "unknown" and
                          len(linked_blocks) > 1)
    recoverable = (observation["ownership_status"] == "option"
                   and observation["completeness"] == "complete")
    return dict(concentration_risk=amount_risk, repeated_occurrence_loss=bool(repeated_loss),
                component_union_risk=component_risk, exact_source_recoverable=recoverable,
                requires_source_review=not recoverable)


async def audit(dsn, include_option_ids=False):
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            options = await conn.fetch("""
                SELECT o.option_id,o.goods_no,o.option_no,o.option_name,o.collected_at,
                       n.ingredients_raw,n.volume,p.product_url,o.delisted_at
                FROM raw_oy_product_option o
                JOIN raw_oy_product p USING(goods_no)
                LEFT JOIN raw_oy_product_notice n USING(goods_no)
                ORDER BY o.option_id
            """)
            legacy = defaultdict(list)
            for row in await conn.fetch("""
                SELECT oi.option_id,i.ingredient_name,i.ingredient_norm,oi.seq
                FROM raw_oy_option_ingredient oi JOIN raw_oy_ingredient i USING(ingredient_id)
            """):
                legacy[row[0]].append(tuple(row[1:]))
        grouped = defaultdict(list)
        for row in options:
            grouped[row["goods_no"]].append(dict(goodsNumber=row["goods_no"],
                optionNumber=row["option_no"], optionName=row["option_name"] or ""))
        sets = defaultdict(set)
        parsed = {}
        for index, row in enumerate(options):
            if os.getenv("G_AUDIT_PROGRESS") and index % 100 == 0:
                print(f"audited {index}/{len(options)}", file=sys.stderr, flush=True)
            option = dict(goodsNumber=row["goods_no"], optionNumber=row["option_no"],
                          optionName=row["option_name"] or "")
            # Only identical notice/option labels share parsing; explicit shade blocks
            # may assign different occurrences to different labels of the same product.
            parse_key = (row["goods_no"], row["option_name"])
            if parse_key not in parsed:
                parsed[parse_key] = ingredient_observation(
                    row["ingredients_raw"], grouped[row["goods_no"]], option,
                    row["collected_at"], row["product_url"] or "", row["volume"] or "")
            observed = parsed[parse_key]
            for kind, flagged in classify(observed, legacy[row["option_id"]]).items():
                if flagged:
                    sets[kind].add(row["option_id"])
        risks = ["concentration_risk", "repeated_occurrence_loss", "component_union_risk"]
        affected = set().union(*(sets[k] for k in risks))
        report = dict(
            universe="all raw options including delisted; DISTINCT option_id",
            total_options=len(options), active_options=sum(r["delisted_at"] is None for r in options),
            counts={k: len(sets[k]) for k in [*risks, "exact_source_recoverable", "requires_source_review"]},
            affected_union=len(affected),
            affected_exact_recoverable=len(affected & sets["exact_source_recoverable"]),
            affected_requires_source_review=len(affected & sets["requires_source_review"]),
            intersections={" & ".join(keys):len(set.intersection(*(sets[k] for k in keys)))
                           for size in (2,3) for keys in combinations(risks,size)},
            examples={k: sorted(sets[k])[:5] for k in risks},
            qualification="component_union_risk is not confirmed constituent ownership; no review approval inferred",
        )
        if include_option_ids:
            report["option_ids"] = {k: sorted(v) for k, v in sets.items()}
            report["option_ids"]["affected_union"] = sorted(affected)
        return report
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-option-ids", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(audit(os.environ["G_AUDIT_DSN"], args.include_option_ids)),
                     ensure_ascii=False, indent=2))
