from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.video_shade_resolution import (
    RawShadeColor,
    RawShadeOption,
    ServingShade,
    resolve_confirmed_shade_fallback,
)
from app.repositories.verified_video_product_repository import VerifiedVideoProductRepository

PRODUCT = "oy-a000000000001"
GOODS = "A000000000001"
OPTION = GOODS + "-001"
RAW = RawShadeOption(OPTION, GOODS, "01", "로즈 베이지")
COLOR = RawShadeColor("#AABBCC", "color_chip")
SHADE = ServingShade(PRODUCT, "01", "로즈베이지", "#aabbcc", None, None)


def resolve(*, options=None, shades=None, color=COLOR):
    return resolve_confirmed_shade_fallback(
        product_id=PRODUCT,
        raw_option_id=OPTION,
        options=[RAW] if options is None else options,
        shades=[SHADE] if shades is None else shades,
        color=color,
    )


def test_unique_legacy_code_and_source_name_hex_agree():
    assert resolve() == "01"


def test_case_only_option_id_and_source_name_hex_agree():
    assert resolve(shades=[replace(SHADE, id=OPTION.lower())]) == OPTION.lower()


def test_shared_raw_code_is_not_guessed():
    assert resolve(options=[RAW, replace(RAW, option_id=GOODS + "-002")]) is None


def test_multiple_serving_id_candidates_are_not_guessed():
    assert resolve(shades=[SHADE, replace(SHADE, id=OPTION.lower())]) is None


def test_missing_or_conflicting_source_evidence_is_not_guessed():
    assert resolve(color=None) is None
    assert resolve(color=RawShadeColor(None, "color_chip")) is None
    assert resolve(color=RawShadeColor("#AABBCC", None)) is None
    assert resolve(color=RawShadeColor("#AABBCC", "none")) is None
    assert resolve(color=RawShadeColor("#000000", "color_chip")) is None
    assert resolve(shades=[replace(SHADE, name="로즈 핑크")]) is None
    assert resolve(options=[replace(RAW, shade_name=None)]) is None
    assert resolve(shades=[replace(SHADE, color_source="placeholder")]) is None
    assert resolve(shades=[replace(SHADE, measure_method="placeholder")]) is None


def test_cannot_use_another_product_or_missing_raw_option():
    assert resolve(shades=[replace(SHADE, product_id="oy-other")]) is None
    assert resolve(options=[replace(RAW, goods_no="A000000000002")]) is None
    assert resolve(options=[]) is None
    assert resolve(shades=[]) is None


def run_mock_coro(coro):
    # Mocked select calls are immediate; no network or real event loop is necessary.
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    finally:
        coro.close()
    raise AssertionError("mock repository query unexpectedly suspended")


def session_with(*rows):
    return SimpleNamespace(
        execute=AsyncMock(
            side_effect=[SimpleNamespace(all=lambda result=result: result) for result in rows]
        )
    )


def test_repository_batches_fallback_and_keeps_original_paths():
    # First query returns the existing exact hit, two mentions of one fallback,
    # and a product-only confirmation. Only the unresolved confirmed option is batch-read.
    confirmed = [
        ("style", "v1", 1, PRODUCT, OPTION, GOODS, OPTION),
        ("style", "v1", 2, PRODUCT, None, GOODS, OPTION),
        ("style", "v2", 1, PRODUCT, None, GOODS, OPTION),
        ("style", "v2", 2, PRODUCT, None, GOODS, None),
    ]
    raw_options = [(OPTION, GOODS, "01", "로즈 베이지")]
    raw_colors = [(OPTION, "#AABBCC", "color_chip")]
    shades = [(PRODUCT, "01", "로즈베이지", "#AABBCC", None, None)]
    curated = [("style", "v3", 1, "yt-curated", None, "merged", "Brand", "Product")]
    direct = [("style", "v4", 1, "yt-direct")]
    session = session_with(confirmed, raw_options, raw_colors, shades, curated, direct)
    links = run_mock_coro(VerifiedVideoProductRepository(session).links(source="style"))

    assert [
        (link.video_id, link.mention_number, link.product_id, link.shade_id) for link in links
    ] == [
        ("v1", 1, PRODUCT, OPTION),
        ("v1", 2, PRODUCT, "01"),
        ("v2", 1, PRODUCT, "01"),
        ("v2", 2, PRODUCT, None),
        ("v3", 1, "yt-curated", None),
        ("v4", 1, "yt-direct", None),
    ]
    assert session.execute.await_count == 6
    assert links[4].link_type == "merged"
    assert links[5].link_type == "direct"


def test_repository_does_not_ignore_latest_missing_raw_color():
    confirmed = [("style", "v1", 1, PRODUCT, None, GOODS, OPTION)]
    raw_options = [(OPTION, GOODS, "01", "로즈 베이지")]
    # The query orders latest first; old colors must not replace the latest NULL.
    raw_colors = [(OPTION, None, "none"), (OPTION, "#AABBCC", "color_chip")]
    shades = [(PRODUCT, "01", "로즈 베이지", "#AABBCC", None, None)]
    session = session_with(confirmed, raw_options, raw_colors, shades, [], [])
    [link] = run_mock_coro(VerifiedVideoProductRepository(session).links())
    assert link.shade_id is None


def test_repository_does_not_batch_read_for_exact_or_product_only_matches():
    confirmed = [
        ("style", "v1", 1, PRODUCT, OPTION, GOODS, OPTION),
        ("style", "v1", 2, PRODUCT, None, GOODS, None),
    ]
    session = session_with(confirmed, [], [])
    links = run_mock_coro(VerifiedVideoProductRepository(session).links())
    assert [link.shade_id for link in links] == [OPTION, None]
    assert session.execute.await_count == 3
