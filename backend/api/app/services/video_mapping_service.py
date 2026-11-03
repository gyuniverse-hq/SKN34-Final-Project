from collections import Counter
from pathlib import Path

from app.repositories.video_mapping_files import API, FIELDS, VideoMappingFiles
from app.services.video_product_matching import (
    RULE_VERSION,
    candidates,
    canonical_brand,
    classify,
    normalize,
)


def key(row: dict) -> tuple[str, str, str]:
    return str(row["source"]), str(row["videoId"]), str(row["number"])


def aliases_from(rows: list[dict]) -> dict[str, str]:
    aliases = {}
    for row in rows:
        alias, standard = row.get("alias", "").strip(), row.get("brand", "").strip()
        if alias and standard:
            norm = normalize(alias)
            if norm in aliases and canonical_brand(aliases[norm], {}) != normalize(standard):
                raise ValueError(f"Conflicting alias: {alias}")
            aliases[norm] = standard
    return aliases


class VideoMappingService:
    def __init__(self, files: VideoMappingFiles | None = None):
        self.files = files or VideoMappingFiles()

    def match(self, catalog_path: Path, output: Path, aliases_path: Path) -> Counter:
        data = self.files.load_sources()
        products = self.files.catalog(catalog_path).products
        aliases = aliases_from(self.files.read_csv(aliases_path))
        previous = {}
        for row in self.files.read_csv(output):
            k = key(row)
            if k in previous:
                raise ValueError(f"Duplicate review row: {k}")
            previous[k] = row
        rows = []
        for source, videos in data.items():
            for video in videos:
                for listed in video["products"]:
                    found = candidates(listed, products, aliases)
                    status, reason = classify(listed, found)
                    best = found[0] if found else None
                    row = {field: "" for field in FIELDS}
                    row.update(
                        source=source,
                        videoId=video["id"],
                        number=listed["number"],
                        brand=listed.get("brand", ""),
                        name=listed.get("name", ""),
                        option=listed.get("option", ""),
                        zone=listed.get("zone", ""),
                        matchStatus=status,
                        score=f"{best.score:.3f}" if best else "",
                        reason=reason,
                        candidateProductId=best.product.id if best else "",
                        candidateProductName=best.product.name_ko if best else "",
                        candidateShadeId=best.shade.id if best and best.shade else "",
                        candidateShadeName=best.shade.name if best and best.shade else "",
                        alt2ProductId=found[1].product.id if len(found) > 1 else "",
                        alt3ProductId=found[2].product.id if len(found) > 2 else "",
                        ruleVersion=RULE_VERSION,
                    )
                    old = previous.get(key(row))
                    if old and any(old.get(x) for x in ("decision", "reviewer", "decidedAt")):
                        for field in ("decision", "reviewer", "decidedAt"):
                            row[field] = old.get(field, "")
                        reviewed_fields = (
                            "candidateProductId",
                            "candidateShadeId",
                            "brand",
                            "name",
                            "option",
                            "zone",
                            "ruleVersion",
                        )
                        if any(
                            str(old.get(field, "")) != str(row[field]) for field in reviewed_fields
                        ) or "candidate_changed" in old.get("reason", ""):
                            row["reason"] += ";candidate_changed"
                    rows.append(row)
        self.files.write_csv(output, rows)
        return Counter(row["matchStatus"] for row in rows)

    def apply(self, catalog_path: Path, review_path: Path, write: bool = False) -> dict:
        data = self.files.load_sources()
        products = {p.id: p for p in self.files.catalog(catalog_path).products}
        rows = self.files.read_csv(review_path)
        by_key = {}
        errors = []
        for row in rows:
            try:
                k = key(row)
            except KeyError:
                errors.append("review CSV missing key columns")
                continue
            if k in by_key:
                errors.append(f"duplicate review row: {k}")
            by_key[k] = row
        counts = Counter()
        observed = set()
        for source, videos in data.items():
            for video in videos:
                for listed in video["products"]:
                    k = (source, video["id"], str(listed["number"]))
                    observed.add(k)
                    row = by_key.get(k)
                    if row is None:
                        errors.append(f"missing review row: {k}")
                        continue
                    decision = row.get("decision", "").strip()
                    if decision not in ("", "reject", "approve_product", "approve_shade"):
                        errors.append(f"{k}: invalid decision")
                        continue
                    mapping = {}
                    if decision.startswith("approve_"):
                        if any(
                            str(row.get(field, "")) != str(listed.get(field, ""))
                            for field in ("brand", "name", "option", "zone")
                        ):
                            errors.append(f"{k}: source product changed since review")
                            continue
                        product = products.get(row.get("candidateProductId", ""))
                        if not product or "candidate_changed" in row.get("reason", ""):
                            errors.append(f"{k}: missing product or candidate changed")
                            continue
                        mapping = {"mappingVerified": True, "catalogProductId": product.id}
                        if decision == "approve_shade":
                            shade = next(
                                (s for s in product.shades if s.id == row.get("candidateShadeId")),
                                None,
                            )
                            if (
                                not shade
                                or shade.measure_method == "placeholder"
                                or shade.color_source == "placeholder"
                            ):
                                errors.append(f"{k}: shade missing, unrelated, or placeholder")
                                continue
                            mapping["catalogShadeId"] = shade.id
                    before = {
                        field: listed[field]
                        for field in ("mappingVerified", "catalogProductId", "catalogShadeId")
                        if field in listed
                    }
                    for field in ("mappingVerified", "catalogProductId", "catalogShadeId"):
                        listed.pop(field, None)
                    listed.update(mapping)
                    if before == mapping:
                        counts["unchanged"] += 1
                    elif mapping:
                        counts["approved"] += 1
                    else:
                        counts["revoked"] += 1
        errors.extend(f"unknown review row: {k}" for k in by_key.keys() - observed)
        if write and not errors:
            self.files.write_sources(data)
        return {"counts": dict(counts), "errors": errors, "written": write and not errors}


def default_catalog() -> Path:
    return API / "seed/catalog.json"
