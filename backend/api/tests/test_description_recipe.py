from app.services.description_recipe_service import recipe_from_description

CHAPTERS = """영상 설명
00:00 인사
0:40 눈썹
1:51 쉐딩
3:55 아이섀도우 시작
4:48 아이라인
5:53 속눈썹
13:35 립, 점찍기
"""


def test_chapters_become_zones_in_time_order_without_guessed_styles() -> None:
    recipe = recipe_from_description("v1", CHAPTERS)
    assert recipe is not None and recipe.review_status == "unreviewed"
    assert [(s.zone, s.start_seconds) for s in recipe.steps] == [
        ("brow", 40),
        ("contour", 111),
        ("eyeshadow", 235),
        ("eyeliner", 288),
        ("mascara", 353),
        ("lip", 815),
    ]
    assert [s.order for s in recipe.steps] == [1, 2, 3, 4, 5, 6]
    assert all(s.style is None for s in recipe.steps)  # "쉐딩" alone names no style


def test_eyelashes_are_not_read_as_brows() -> None:
    recipe = recipe_from_description("v1", "0:00 시작\n1:00 속눈썹\n2:00 마무리\n")
    assert recipe is not None
    assert [s.zone for s in recipe.steps] == ["mascara"]


def test_a_style_is_read_only_from_the_same_chapter_line() -> None:
    text = "0:00 시작\n1:00 턱선 쉐딩\n2:00 하이라이터 애교살\n3:00 끝\n"
    recipe = recipe_from_description("v1", text)
    assert recipe is not None
    styles = {s.zone: s.style for s in recipe.steps}
    assert styles == {"contour": "jawline", "highlighter": "under_eye_smile"}


def test_chapter_styles_for_liner_blush_shadow_and_lip() -> None:
    text = (
        "0:00 시작\n1:00 캣윙 아이라인\n2:00 광대 블러셔\n3:00 쉬머 아이섀도\n"
        "4:00 오버립\n5:00 슬림 마스카라\n6:00 끝\n"
    )
    recipe = recipe_from_description("v1", text)
    assert recipe is not None
    styles = {s.zone: s.style for s in recipe.steps}
    assert styles == {
        "eyeliner": "cat_wing",
        "blush": "apple",
        "eyeshadow": "shimmer",
        "lip": "overlip",
        "mascara": "slim",
    }


def test_a_chapter_can_name_two_zones() -> None:
    recipe = recipe_from_description("v1", "0:00 시작\n7:08 베이스, 쉐딩\n9:00 립\n")
    assert recipe is not None
    assert {(s.zone, s.start_seconds) for s in recipe.steps} == {
        ("foundation", 428),
        ("contour", 428),
        ("lip", 540),
    }


def test_too_few_chapters_or_no_makeup_words_gives_no_recipe() -> None:
    assert recipe_from_description("v1", "0:00 시작\n1:00 쉐딩\n") is None  # 2 chapters
    assert recipe_from_description("v1", "0:00 a\n1:00 b\n2:00 c\n") is None  # no zone words
    assert recipe_from_description("v1", "쉐딩 방법 설명") is None
