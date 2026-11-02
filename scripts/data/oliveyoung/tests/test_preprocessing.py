"""Regressions observed in the first skincare snapshot."""

import json
import sys
import tempfile
from pathlib import Path

COLLECTORS = Path(__file__).resolve().parents[1] / "collectors"
sys.path.insert(0, str(COLLECTORS.parent))
sys.path.insert(0, str(COLLECTORS))

import collect_snapshot as snapshot
import oliveyoung_erd_v30 as makeup
import oliveyoung_skincare_v2 as skincare


def test_corrupted_ingredient_tokens_are_not_linked():
    invalid = (
        "펜타에리스리틸테트라-다이-T\x02부틸하이드록시하이드로신나메이트",
        "오카무라\ufffd\ufffd\ufffd실말추출물",
        "루틴 \ufeff*SUPER CICA 7™",
    )
    assert all(makeup.clean_ingredient(value) == "" for value in invalid)
    assert makeup.clean_ingredient("정제수") == "정제수"
    assert makeup.clean_ingredient("1,2-헥산다이올") == "1,2-헥산다이올"


def test_number_commas_are_split_only_at_ingredient_boundaries():
    """성분명 안의 쉼표(로칸트·천 단위)는 보호하고 성분 경계만 쪼갠다."""
    # 이름 꼬리가 숫자인 성분 뒤에 로칸트 성분이 오는 경우(유령 성분 '2-헥산다이올'의 원인)
    assert makeup.ingredient_list(
        "솔비탄아이소스테아레이트, 폴리솔베이트60, 1,2-헥산다이올, 글리세린"
    ) == ["솔비탄아이소스테아레이트", "폴리솔베이트60", "1,2-헥산다이올", "글리세린"]
    assert makeup.ingredient_list("글리세레스-26, 1,2-헥산다이올, 세테아레스-20") == [
        "글리세레스-26",
        "1,2-헥산다이올",
        "세테아레스-20",
    ]
    # 이름 중간·앞머리의 로칸트는 쪼개지 않는다
    for single in (
        "다이에틸헥실2,6-나프탈레이트",
        "비스-에톡시다이글라이콜사이클로헥산1,4-다이카복실레이트",
        "황산톨루엔-2,5-디아민",
        "2-올레아미도-1,3-옥타데칸다이올",
    ):
        assert makeup.ingredient_list(single) == [single]
    # 함량 표기의 천 단위 구분 쉼표도 성분 경계가 아니다
    assert makeup.ingredient_list("정제수, 자작나무수액(10,000ppm), 호호바에스터") == [
        "정제수",
        "자작나무수액(10,000ppm)",
        "호호바에스터",
    ]
    # 쉼표 주변 공백은 기존과 같이 정규화한다(같은 성분이 두 표기로 갈라지지 않도록)
    assert makeup.ingredient_list("글리세린, 1, 2-헥산다이올") == ["글리세린", "1,2-헥산다이올"]
    # 하이픈 없는 변형 표기도 보호한다
    assert makeup.ingredient_list("정제수, 1,2헥산다이올, 글리세린") == [
        "정제수",
        "1,2헥산다이올",
        "글리세린",
    ]


def test_spf_volume_is_not_treated_as_sun_protection_factor():
    notice = {"main_spec": "모든피부", "usage_guide": ""}
    gift = skincare.skincare_attr(
        "A000000263071", "포마드 100ml 기획 (크림 SPF 5ml)", notice, {}, ""
    )
    sunscreen = skincare.skincare_attr(
        "A000000224171", "선 에센스SPF50+PA++++ 50ml", notice, {}, ""
    )
    assert gift["spf"] == ""
    assert sunscreen["spf"] == "50+"


def test_notice_volume_html_break_is_plain_text():
    assert makeup.clean_notice_volume("본품 180ml <br>증정 120ml") == (
        "본품 180ml \n증정 120ml"
    )


def test_only_standalone_known_non_ingredient_text_is_dropped_and_reported():
    dropped = set()
    parsed = makeup.ingredient_list(
        "전성분명,정제수,전성분 정제수,제품에는 이상이 없습니다",
        on_review=dropped.add,
    )
    assert parsed == ["정제수", "전성분 정제수"]
    assert dropped == {"전성분명", "제품에는 이상이 없습니다"}
    assert makeup.clean_ingredient("전성분 (시트) 트레할로오스") != ""


def test_only_confirmed_functional_no_markers_become_no():
    notice = {"main_spec": "모든피부", "usage_guide": ""}

    def functional(raw):
        return skincare.skincare_attr(
            "A000000015117", "상품", notice, {skincare.FUNCTIONAL_KEY: raw}, ""
        )

    assert functional("|N")["is_functional"] == "N"
    assert functional("■ 무")["is_functional"] == "N"
    assert functional("■ 무")["functional_raw"] == "■ 무"
    assert functional("판정 불명")["is_functional"] == "?"
    assert functional("■ 무, 기타 표시")["is_functional"] == "?"


def test_old_snapshot_cannot_be_mistaken_for_new_collector_output():
    with tempfile.TemporaryDirectory() as directory:
        manifest = {
            "kind": "skincare",
            "mode": "full",
            "script_version": "skincare-v2-db",
            "listing_complete": True,
            "complete": True,
        }
        (Path(directory) / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        try:
            snapshot.collect("skincare", Path(directory))
        except ValueError as exc:
            assert "different collector version" in str(exc)
        else:
            raise AssertionError("Old snapshot was accepted as a new collection")
