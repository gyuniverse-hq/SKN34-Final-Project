from app.services.look_video_registration_service import (
    mention_only_videos,
    plan_registrations,
    primary_start,
)


def video(youtube_id: str, **extra) -> dict:
    return {
        "video_id": youtube_id,
        "video_url": f"https://www.youtube.com/watch?v={youtube_id}",
        "title": f"Look {youtube_id}",
        "channel": "Channel",
        "thumbnail_url": f"https://i.ytimg.com/vi/{youtube_id}/maxresdefault.jpg",
        "description": "",
        "origins": ["db_mention_only"],
        "db_video_id": None,
        **extra,
    }


def test_only_mention_videos_without_a_row_are_registered() -> None:
    inventory = {
        "videos": [
            video("new1"),
            video("pilot", origins=["db_registered"], db_video_id="VIDEO-001"),
            video("catalog_only", origins=["style_catalog"]),
        ]
    }
    assert [item["video_id"] for item in mention_only_videos(inventory)] == ["new1"]


def test_primary_start_takes_the_earliest_primary_segment() -> None:
    tag = {
        "finished_look_segments": [
            {"start_seconds": 212, "role": "primary"},
            {"start_seconds": 5, "role": "supporting"},
            {"start_seconds": 40, "role": "primary"},
        ]
    }
    assert primary_start(tag) == 40
    assert primary_start(None) == 0
    assert primary_start({"finished_look_segments": []}) == 0


def test_new_videos_continue_after_every_used_id_and_pair_with_a_look() -> None:
    planned = plan_registrations(
        [video("a"), video("b")],
        {"b": {"finished_look_segments": [{"start_seconds": 30, "role": "primary"}]}},
        existing={"pilot": "VIDEO-001"},
        used_ids=["VIDEO-001", "VIDEO-003", "LOOK-001", "LOOK-004"],
    )
    assert [(item.id, item.look_id, item.start_seconds) for item in planned] == [
        ("VIDEO-005", "LOOK-005", 0),
        ("VIDEO-006", "LOOK-006", 30),
    ]
    assert all(item.is_new and item.analysis_status == "registered" for item in planned)


def test_rerun_keeps_ids_already_given() -> None:
    planned = plan_registrations(
        [video("a"), video("b")],
        {},
        existing={"a": "VIDEO-004"},
        used_ids=["VIDEO-003", "VIDEO-004", "LOOK-004"],
    )
    assert [(item.id, item.is_new) for item in planned] == [
        ("VIDEO-004", False),
        ("VIDEO-005", True),
    ]


def test_missing_metadata_gets_placeholders() -> None:
    (item,) = plan_registrations(
        [video("x", title="", channel="", thumbnail_url="")], {}, existing={}, used_ids=[]
    )
    assert item.title == "YouTube video x"
    assert item.thumbnail_url == "https://i.ytimg.com/vi/x/hqdefault.jpg"
    assert item.channel_name == ""
    assert item.analysis_status == "metadata_unavailable"
    assert item.description is None
