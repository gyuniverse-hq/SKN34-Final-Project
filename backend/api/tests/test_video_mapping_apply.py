import json
from pathlib import Path

from app.repositories.video_mapping_files import VideoMappingFiles
from app.services.video_mapping_service import VideoMappingService
from tests.test_video_product_matching import product


def fixture(tmp_path: Path):
    sources = {}
    for name in ("celebrity", "style"):
        paths = (tmp_path / f"{name}-server.json", tmp_path / f"{name}-client.json")
        video = [
            {
                "id": f"{name}-id",
                "products": [
                    {
                        "number": 1,
                        "brand": "브랜드",
                        "name": "립 워터 틴트",
                        "option": "04호",
                        "zone": "립",
                    }
                ],
            }
        ]
        for path in paths:
            path.write_text(
                json.dumps(video, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        sources[name] = paths
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps({"products": [product().model_dump(by_alias=True)]}, ensure_ascii=False),
        encoding="utf-8",
    )
    aliases = tmp_path / "aliases.csv"
    aliases.write_text("alias,brand\n", encoding="utf-8")
    return (
        VideoMappingService(VideoMappingFiles(sources)),
        sources,
        catalog,
        aliases,
        tmp_path / "review.csv",
    )


def test_approve_product_and_shade_dry_run_and_idempotence(tmp_path):
    service, sources, catalog, aliases, review = fixture(tmp_path)
    service.match(catalog, review, aliases)
    rows = service.files.read_csv(review)
    rows[0]["decision"] = "approve_shade"
    rows[1]["decision"] = "approve_product"
    service.files.write_csv(review, rows)
    before = sources["celebrity"][0].read_bytes()
    dry = service.apply(catalog, review)
    assert dry["counts"]["approved"] == 2 and not dry["written"]
    assert sources["celebrity"][0].read_bytes() == before
    assert service.apply(catalog, review, write=True)["written"]
    for source, (server, client) in sources.items():
        assert server.read_bytes() == client.read_bytes()
        mapping = json.loads(server.read_text(encoding="utf-8"))[0]["products"][0]
        assert mapping["mappingVerified"] and mapping["catalogProductId"] == "p1"
        assert ("catalogShadeId" in mapping) == (source == "celebrity")
    assert service.apply(catalog, review, write=True)["counts"]["unchanged"] == 2


def test_invalid_shade_refuses_all_writes_and_candidate_changed(tmp_path):
    service, sources, catalog, aliases, review = fixture(tmp_path)
    service.match(catalog, review, aliases)
    rows = service.files.read_csv(review)
    rows[0].update(decision="approve_shade", candidateShadeId="not-a-shade")
    service.files.write_csv(review, rows)
    before = {p: p.read_bytes() for paths in sources.values() for p in paths}
    result = service.apply(catalog, review, write=True)
    assert result["errors"] and not result["written"]
    assert before == {p: p.read_bytes() for paths in sources.values() for p in paths}
    rows[0].update(candidateShadeId="s1", reason="candidate_changed")
    service.files.write_csv(review, rows)
    assert service.apply(catalog, review, write=True)["errors"]


def test_changed_candidate_preserves_review_but_blocks_apply(tmp_path):
    service, _, catalog, aliases, review = fixture(tmp_path)
    service.match(catalog, review, aliases)
    rows = service.files.read_csv(review)
    rows[0].update(
        decision="approve_shade",
        reviewer="reviewer",
        decidedAt="2026-01-01",
        candidateShadeId="old",
    )
    service.files.write_csv(review, rows)
    service.match(catalog, review, aliases)
    row = service.files.read_csv(review)[0]
    assert row["decision"] == "approve_shade" and row["reviewer"] == "reviewer"
    assert "candidate_changed" in row["reason"]
    assert service.apply(catalog, review, write=True)["errors"]


def test_rejection_removes_existing_mapping(tmp_path):
    service, sources, catalog, aliases, review = fixture(tmp_path)
    service.match(catalog, review, aliases)
    rows = service.files.read_csv(review)
    rows[0]["decision"] = "approve_shade"
    service.files.write_csv(review, rows)
    assert service.apply(catalog, review, write=True)["written"]
    rows[0]["decision"] = "reject"
    service.files.write_csv(review, rows)
    assert service.apply(catalog, review, write=True)["counts"]["revoked"] == 1
    item = json.loads(sources["celebrity"][0].read_text(encoding="utf-8"))[0]["products"][0]
    assert not {"mappingVerified", "catalogProductId", "catalogShadeId"} & item.keys()


def test_placeholder_shade_cannot_be_approved(tmp_path):
    service, sources, catalog, aliases, review = fixture(tmp_path)
    service.match(catalog, review, aliases)
    rows = service.files.read_csv(review)
    rows[0]["decision"] = "approve_shade"
    service.files.write_csv(review, rows)
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    payload["products"][0]["shades"][0]["measureMethod"] = "placeholder"
    catalog.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    before = sources["celebrity"][0].read_bytes()
    result = service.apply(catalog, review, write=True)
    assert result["errors"] and not result["written"]
    assert sources["celebrity"][0].read_bytes() == before
