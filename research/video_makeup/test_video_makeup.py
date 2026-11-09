"""Synthetic checks: draw a known wing and blush on a flat skin image over a real face mesh, then measure them.

Run: research/ar_evaluation/.venv/Scripts/python.exe -m pytest research/video_makeup -q
The fixture holds only the 468 mesh points (no image).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from captions import SHADE, Speech, caption_steps, names_product, parse_json3, pick_track  # noqa: E402
from common import BLUSH_RADII, eye_frame, face_width, from_eye  # noqa: E402
from gemini_steps import vote  # noqa: E402
from measure import blush_templates, change, lid_curves, measure_blush, measure_liner, measure_liner_eye, warp_to  # noqa: E402
from timeline import find_rise  # noqa: E402

FIX = json.loads((Path(__file__).parent / "fixtures" / "face_mesh.json").read_text())
PTS = np.array(FIX["points"], dtype=np.float32)
SHAPE = (FIX["height"], FIX["width"])
SKIN = (222, 196, 186)
LINER = (35, 28, 28)


def skin() -> np.ndarray:
    return np.full((*SHAPE, 3), SKIN, np.uint8)


def draw_liner(img: np.ndarray, k: int, length: float, angle: float, thickness: float, lower: bool = False) -> None:
    frame = eye_frame(PTS, k)
    uu, top, lu, low = lid_curves(PTS, k, frame)
    us = np.linspace(-1.0, 0.0, 40)
    band = np.concatenate([np.stack([us, np.interp(us, uu, top)], 1),
                           np.stack([us[::-1], np.interp(us[::-1], uu, top) + thickness], 1)])
    cv2.fillPoly(img, [np.round(from_eye(band, frame)).astype(np.int32)], LINER)
    if length > 0:
        tip = [length * math.cos(math.radians(angle)), length * math.sin(math.radians(angle))]
        tri = np.array([[0.0, 0.0], [0.0, thickness], tip])
        cv2.fillPoly(img, [np.round(from_eye(tri, frame)).astype(np.int32)], LINER)
    if lower:
        lband = np.concatenate([np.stack([us, np.interp(us, lu, low)], 1),
                                np.stack([us[::-1], np.interp(us[::-1], lu, low) - 0.05], 1)])
        cv2.fillPoly(img, [np.round(from_eye(lband, frame)).astype(np.int32)], LINER)


def draw_blush(img: np.ndarray, centers: list[np.ndarray], radius: float) -> np.ndarray:
    yy, xx = np.mgrid[0:SHAPE[0], 0:SHAPE[1]]
    g = np.zeros(SHAPE, np.float32)
    for c in centers:
        g = np.maximum(g, np.exp(-((xx - c[0]) ** 2 + (yy - c[1]) ** 2) / (2 * radius ** 2)))
    pink = np.array([236, 120, 135], np.float32)
    return (img * (1 - 0.45 * g[..., None]) + pink * 0.45 * g[..., None]).astype(np.uint8)


def measure_both(after: np.ndarray):
    before = skin()
    covered = np.ones(SHAPE, bool)
    ch = change(before, after, covered, PTS)
    eyes = [measure_liner_eye(ch, PTS, k) for k in (0, 1)]
    return measure_liner(eyes), measure_blush(ch, PTS)[0]


@pytest.mark.parametrize("length,angle,thickness,chip", [(0.3, 15, 0.1, "cat_wing"), (0.12, -10, 0.09, "puppy")])
def test_wing_is_measured_in_eye_widths_and_degrees(length, angle, thickness, chip):
    img = skin()
    for k in (0, 1):
        draw_liner(img, k, length, angle, thickness)
    liner, _ = measure_both(img)
    g = liner["geometry"]
    assert abs(g["length"] - length) < 0.03
    assert abs(g["angle"] - angle) < 4
    assert abs(g["thickness"] - thickness) < 0.025
    assert g["linerLower"] is False
    assert liner["nearestChip"] == chip


def test_no_tail_and_lower_line():
    img = skin()
    for k in (0, 1):
        draw_liner(img, k, 0.0, 0, 0.06, lower=True)
    liner, _ = measure_both(img)
    assert liner["geometry"]["length"] < 0.02
    assert liner["geometry"]["linerLower"] is True
    assert liner["nearestChip"] == "under_point"


@pytest.mark.parametrize("placement", ["apple", "side", "under_eye"])
def test_blush_placement_follows_the_ar_templates(placement):
    centers = [blush_templates(PTS, k)[placement] for k in (0, 1)]
    r0 = face_width(PTS) * math.sqrt(BLUSH_RADII[0] * BLUSH_RADII[1])
    _, blush = measure_both(draw_blush(skin(), centers, 0.5 * r0))
    assert blush["geometry"]["blushPlacement"] == placement


def test_bigger_blush_reads_bigger_and_nothing_reads_nothing():
    centers = [blush_templates(PTS, k)["apple"] for k in (0, 1)]
    r0 = face_width(PTS) * math.sqrt(BLUSH_RADII[0] * BLUSH_RADII[1])
    _, small = measure_both(draw_blush(skin(), centers, 0.35 * r0))
    _, big = measure_both(draw_blush(skin(), centers, 0.6 * r0))
    assert big["geometry"]["blushSize"] > small["geometry"]["blushSize"] * 1.3
    _, none = measure_both(skin())
    assert "geometry" not in none


def test_exposure_change_alone_is_not_makeup():
    brighter = np.clip(skin().astype(np.int16) + 12, 0, 255).astype(np.uint8)
    liner, blush = measure_both(brighter)
    assert "geometry" not in liner and "geometry" not in blush


def test_a_caption_over_the_chin_is_not_blush():
    after = skin()
    chin = PTS[[17, 152]].mean(0).astype(int)
    w = int(0.25 * face_width(PTS))
    cv2.rectangle(after, (chin[0] - w, chin[1] - w // 3), (chin[0] + w, SHAPE[0] - 1), (250, 250, 250), -1)
    liner, blush = measure_both(after)
    assert "geometry" not in blush and "geometry" not in liner


def test_warp_onto_the_same_mesh_keeps_the_image():
    rng = np.random.default_rng(0)
    img = cv2.GaussianBlur(rng.integers(0, 255, (*SHAPE, 3), dtype=np.uint8), (0, 0), 3)
    out, covered = warp_to(img, PTS, PTS, SHAPE)
    assert covered.sum() > 0.8 * cv2.contourArea(cv2.convexHull(PTS))
    assert float(np.abs(out[covered].astype(int) - img[covered].astype(int)).mean()) < 2


def test_vote_keeps_what_most_runs_agree_on():
    p = {"brand": "롬앤", "name": "쥬시 래스팅 틴트", "shade": "25", "seconds": 300}
    runs = [
        {"steps": [{"zone": "lip", "start_seconds": 300, "end_seconds": 330, "products": [p]},
                   {"zone": "blush", "start_seconds": 200}]},
        {"steps": [{"zone": "lip", "start_seconds": 304, "end_seconds": 332, "products": [{**p, "shade": "25"}]}]},
        {"steps": [{"zone": "lip", "start_seconds": 310, "products": [{**p, "shade": None}]}]},
    ]
    steps = vote(runs)
    assert [s["zone"] for s in steps] == ["lip"]
    assert steps[0]["start_seconds"] == 304 and steps[0]["end_seconds"] == 331
    assert steps[0]["products"][0]["shade"] == "25"


def test_captions_pick_the_creator_track_never_a_translation():
    info = {"subtitles": {"en-FmoQciUtYSc": [], "ko-FmoQciUtYSc": []},
            "automatic_captions": {"ko": [], "ko-en-FmoQciUtYSc": []}}
    assert pick_track(info) == ("ko-FmoQciUtYSc", "manual")
    assert pick_track({"subtitles": {}, "automatic_captions": {"ko": [], "ko-en": []}}) == ("ko", "auto")
    assert pick_track({"subtitles": {}, "automatic_captions": {"en": []}}) is None


def test_json3_cues_keep_times_and_drop_sound_tags():
    raw = json.dumps({"events": [
        {"tStartMs": 100, "dDurationMs": 2000, "segs": [{"utf8": "[음악]"}]},
        {"tStartMs": 16600, "dDurationMs": 2500, "segs": [{"utf8": "안녕하세요 "}, {"utf8": "지유입니다"}]},
        {"tStartMs": 19000, "segs": [{"utf8": "\n"}]},
    ]})
    assert parse_json3(raw) == [{"t": 16.6, "end": 19.1, "text": "안녕하세요 지유입니다"}]


def test_caption_step_is_the_densest_run_not_the_intro():
    cues = [{"t": 20.0, "text": "오늘은 아이라인 포인트 메이크업"},
            {"t": 200.0, "text": "립라이너로 입술 라인을 따줄게요"},
            {"t": 400.0, "text": "아이라인을 그려줄 건데요"},
            {"t": 420.0, "text": "아이라이너 꼬리는 길게"},
            {"t": 450.0, "text": "라인 끝을 정리해 줍니다 아이라인 완성"},
            {"t": 470.0, "text": "블러셔는 광대 위주로"}]
    steps = caption_steps(cues)
    assert steps["eyeliner"]["start_seconds"] == 400 and steps["eyeliner"]["mentions"] == 3
    assert steps["blush"]["start_seconds"] == 470


def test_products_are_named_by_brand_and_part_of_the_name():
    pencil = {"brand": "클리오", "name": "벨벳 립 펜슬 04 텐 브라운"}
    shading = {"brand": "클리오", "name": "소프트 쉐딩 스틱"}
    said = "여러분 제가 요즘에 이 클리오 립펜슬 있잖아요 4호 텐브라운 컬러가"
    assert names_product(pencil, said)[0]
    assert not names_product(shading, said)[0]
    concealer = {"brand": "3CE", "name": "스킨 핏 스킨 커버 리퀴드 컨실러 화이트"}
    assert not names_product(concealer, "그리고 컨실러 작업을 해주는데")[0]
    junk = {"brand": "확인 필요", "name": "발림성,픽싱력,유지력 모두 다 개인적으로 좋을것 같아요"}
    speech = Speech([{"text": t} for t in ("좋을 것 같아요", "예쁠 것 같아요", "좋을 것 같고요", "생각해주시면 좋을 것 같아요")])
    assert not names_product(junk, "생각해주시면 좋을 것 같아요", speech)[0]


def test_shade_words():
    found = {m.replace(" ", "") for m in SHADE.findall("19호 컨실러랑 21N 쿠션, 03번 컬러, #02 립")}
    assert found == {"19호", "21N", "03번", "#02"}


def test_rise_finds_the_step():
    good = [{"t": float(t), "wing": (10.0 if t >= 30 else 2.0) + 0.3 * math.sin(t)} for t in range(60)]
    rise = find_rise(good, "wing")
    assert abs(rise["t"] - 30) <= 1
    assert rise["rise"] > 7
