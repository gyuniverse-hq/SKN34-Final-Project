from app.repositories.makeup_look_catalog_repository import CATALOG_FIELDS
from app.services.makeup_look_catalog_service import plan_catalog


def product(number: int, **extra) -> dict:
    return {"number": number, "brand": "B", "name": f"P{number}", "option": "", **extra}


STYLE = [
    {
        "id": "sty1",
        "title": "Vanilla",
        "group": "G1",
        "tag": "#t1",
        "videoUrl": "u",
        "products": [product(1)],
    },
    {"id": "sty2", "title": "Cool", "group": "G2", "tag": "#t2", "videoUrl": "u", "products": []},
]
CELEB = [
    {
        "id": "cel1",
        "celebrityId": "karina",
        "number": 2,
        "startSeconds": 15,
        "linkStatus": "metadata_available",
        "title": "Karina look",
        "channelName": "ch",
        "products": [product(1, sourceType="제품제공")],
    },
    {
        "id": "cel2",
        "celebrityId": "haerin",
        "number": 3,
        "startSeconds": 0,
        "linkStatus": "needs_review",
        "title": "",
        "channelName": "",
        "products": [],
    },
]


def look(look_id: str, youtube_id: str, **values) -> dict:
    row = {"look_id": look_id, "youtube_id": youtube_id, "video_title": f"video {youtube_id}"}
    row.update(dict.fromkeys(CATALOG_FIELDS))
    row["is_catalog_published"] = False
    row.update(values)
    return row


def looks() -> list[dict]:
    return [
        look("LOOK-001", "sty1"),
        look("LOOK-002", "S2nXySh1WuU"),
        look("LOOK-003", "sty2"),
        look("LOOK-004", "cel1"),
        look("LOOK-005", "cel2"),
        look("LOOK-006", "new-video"),
    ]


def mentions() -> dict:
    return {
        ("style", "sty1", 1): {"source_row_id": "style|sty1|1", "source_payload": None},
        ("celebrity", "cel1", 1): {"source_row_id": "celebrity|cel1|1", "source_payload": None},
    }


def test_curated_looks_are_classified_and_the_rest_stay_unclassified() -> None:
    plan = plan_catalog(STYLE, CELEB, looks(), mentions())
    assert plan.ok
    assert plan.looks["LOOK-001"] == {
        **dict.fromkeys(CATALOG_FIELDS),
        "look_type": "style",
        "style_group": "G1",
        "style_tag": "#t1",
        "catalog_title": "Vanilla",
        "catalog_position": 1,
        "is_catalog_published": True,
    }
    assert plan.looks["LOOK-003"]["catalog_position"] == 2
    assert plan.looks["LOOK-004"] == {
        **dict.fromkeys(CATALOG_FIELDS),
        "look_type": "celebrity",
        "celebrity_id": "karina",
        "catalog_title": "Karina look",
        "catalog_position": 2,
        "catalog_start_seconds": 15,
        "catalog_link_status": "metadata_available",
        "is_catalog_published": True,
    }
    assert plan.unclassified == ["LOOK-006"]


def test_empty_curated_title_uses_the_video_title_and_keeps_needs_review() -> None:
    values = plan_catalog(STYLE, CELEB, looks(), mentions()).looks["LOOK-005"]
    assert values["catalog_title"] == "video cel2"
    assert values["catalog_link_status"] == "needs_review"


def test_the_actor_look_is_classified_but_not_published() -> None:
    values = plan_catalog(STYLE, CELEB, looks(), mentions()).looks["LOOK-002"]
    assert values["look_type"] == "celebrity" and values["celebrity_id"] == "goyounjung"
    assert values["catalog_title"] == "video S2nXySh1WuU"
    assert values["catalog_position"] is None and values["is_catalog_published"] is False


def test_curated_products_are_kept_as_payloads_exactly() -> None:
    plan = plan_catalog(STYLE, CELEB, looks(), mentions())
    assert plan.payloads == [
        ("style|sty1|1", STYLE[0]["products"][0]),
        ("celebrity|cel1|1", CELEB[0]["products"][0]),
    ]


def test_a_rerun_after_loading_changes_nothing() -> None:
    first = plan_catalog(STYLE, CELEB, looks(), mentions())
    loaded = [{**row, **first.looks.get(row["look_id"], {})} for row in looks()]
    filled = mentions()
    for mention in filled.values():
        mention["source_payload"] = dict(first.payloads)[mention["source_row_id"]]
    second = plan_catalog(STYLE, CELEB, loaded, filled)
    assert second.ok and not second.looks and not second.payloads
    assert (second.unchanged_looks, second.unchanged_payloads) == (5, 2)


def test_values_edited_in_the_database_are_never_overwritten() -> None:
    edited = looks()
    edited[0].update(look_type="style", style_group="G1", style_tag="#t1", catalog_title="Edited")
    filled = mentions()
    filled[("style", "sty1", 1)]["source_payload"] = {"number": 1, "name": "edited"}
    plan = plan_catalog(STYLE, CELEB, edited, filled)
    assert not plan.ok
    assert any(c.startswith("LOOK-001 already differs") for c in plan.conflicts)
    assert "style|sty1|1 payload differs in the database" in plan.conflicts


def test_missing_looks_and_mentions_are_reported() -> None:
    plan = plan_catalog(STYLE, CELEB, looks()[1:], {})
    assert "curated video without a makeup look: sty1" in plan.conflicts
    assert any("without a raw mention" in c for c in plan.conflicts)
