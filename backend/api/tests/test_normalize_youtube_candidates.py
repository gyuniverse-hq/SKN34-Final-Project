from app.jobs.normalize_youtube_candidates import (
    classify_product,
    parse_subject_and_style,
    split_products,
)


def test_known_subject_misclassifications_are_corrected():
    assert parse_subject_and_style("aaYar3I6yQA", "인물: 레이") == (
        "",
        "웜톤이 하는 쿨 그레이 메이크업",
        "corrected",
    )
    assert parse_subject_and_style("ksFyMbfJcww", "인물: 레이") == (
        "유정",
        "",
        "corrected",
    )
    assert parse_subject_and_style("9p0SKbMRhDc", "룩 스타일: 리아 커버") == (
        "리아",
        "",
        "corrected",
    )
    assert parse_subject_and_style("yWzg365rzMw", "룩 스타일: 아오이 유우 스타일 메이크업") == (
        "아오이 유우",
        "",
        "corrected",
    )
    assert parse_subject_and_style("mcA6C14VuTU", "인물: 카리나") == (
        "",
        "다이소 개강 메이크업",
        "corrected",
    )


def test_product_segments_are_split_without_guessing_brand_or_shade():
    assert split_products("롬앤 립 틴트 / 클리오 아이 팔레트") == [
        "롬앤 립 틴트",
        "클리오 아이 팔레트",
    ]


def test_product_categories_and_non_product_noise_are_flagged():
    lip = classify_product("롬앤 쥬시 래스팅 립 틴트")
    assert (lip.category, lip.makeup_zone, lip.review_status) == (
        "lip",
        "lip",
        "needs_review",
    )
    eyeshadow = classify_product("클리오 프로 아이 팔레트")
    assert (eyeshadow.category, eyeshadow.makeup_zone) == ("eye", "eyeshadow")
    brush_liner = classify_product("에뛰드 브러쉬 라이너")
    assert brush_liner.category == "eye"
    cream_blush = classify_product("홀리카 틴티드 밀크 크림 블러쉬")
    assert (cream_blush.category, cream_blush.makeup_zone) == ("cheek", "blush")
    music = classify_product("Music by http://example.com")
    assert music.review_status == "needs_review"
    assert music.exclusion_reason == "non_product_content"
    accessory = classify_product("렌즈미 원데이 렌즈")
    assert (accessory.category, accessory.review_status) == (
        "accessory",
        "needs_review",
    )
    unknown = classify_product("확인되지 않은 제품명")
    assert (unknown.category, unknown.review_status) == ("unknown", "needs_review")
