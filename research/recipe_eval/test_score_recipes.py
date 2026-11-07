import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from score_recipes import lcs_len, score, score_video  # noqa: E402


def step(zone, start=None, style=None):
    return {"zone": zone, "startSeconds": start, "style": style}


def test_perfect_match_scores_one() -> None:
    gold = [step("foundation", 10), step("contour", 60, "jawline"), step("lip", 120)]
    r = score_video(gold, gold, 10)
    assert (r["precision"], r["recall"], r["f1"], r["order"], r["time"], r["style"]) == (1, 1, 1, 1, 1, 1)


def test_missing_and_extra_zones_lower_precision_and_recall() -> None:
    gold = [step("foundation"), step("contour"), step("lip")]
    pred = [step("foundation"), step("blush")]
    r = score_video(pred, gold, 10)
    assert r["precision"] == 0.5 and abs(r["recall"] - 1 / 3) < 1e-9
    assert r["time"] is None and r["style"] is None  # nothing to compare yet


def test_order_uses_the_longest_common_subsequence() -> None:
    assert lcs_len(["a", "b", "c"], ["a", "c", "b"]) == 2
    gold = [step("foundation"), step("contour"), step("lip")]
    pred = [step("contour"), step("foundation"), step("lip")]
    assert abs(score_video(pred, gold, 10)["order"] - 2 / 3) < 1e-9


def test_time_tolerance_and_missing_style_counts_as_wrong() -> None:
    gold = [step("contour", 60, "jawline"), step("highlighter", 100, "nose_tip")]
    pred = [step("contour", 68, None), step("highlighter", 140, "nose_tip")]
    r = score_video(pred, gold, 10)
    assert r["time"] == 0.5  # 8 s off is inside the tolerance, 40 s is not
    assert r["style"] == 0.5  # a missing predicted style is wrong


def test_score_reads_review_entries_and_ignores_videos_without_gold() -> None:
    pred = [
        {"video_id": "a", "recipe": {"steps": [{"zone": "lip", "start_seconds": 5, "style": None}]}},
        {"video_id": "b", "recipe": {"steps": []}},
    ]
    gold = [{"videoId": "a", "steps": [step("lip", 5)]}, {"videoId": "c", "steps": [step("lip")]}]
    report = score(pred, gold)
    assert report["videos_scored"] == 1 and report["videos_missing_in_pred"] == ["c"]
    assert report["mean"]["f1"] == 1
