import json

import httpx
import pytest

from app.clients.gemini_client import GeminiClient
from app.core.errors import UpstreamError
from app.schemas.look_recipe import RecipeDraft, ReviewEntry
from app.services.look_recipe_service import LookRecipeService, vote_recipes

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def draft(*steps: dict) -> RecipeDraft:
    return RecipeDraft.model_validate({"steps": list(steps)})


def reply(*steps: dict) -> dict:
    text = json.dumps({"steps": list(steps)})
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_vote_keeps_zones_and_styles_a_majority_agrees_on() -> None:
    runs = [
        draft(
            {"zone": "contour", "start_seconds": 30, "style": "jawline", "intensity": 0.6},
            {"zone": "highlighter", "start_seconds": 90, "style": "nose_tip", "intensity": 0.4},
        ),
        draft(
            {"zone": "contour", "start_seconds": 34, "style": "jawline", "intensity": 0.8},
            {"zone": "highlighter", "start_seconds": 80, "style": "cupid_bow"},
            {"zone": "lip", "start_seconds": 120},
        ),
        draft(
            {"zone": "contour", "start_seconds": 32, "style": "nose", "intensity": 0.7},
            {"zone": "highlighter", "start_seconds": 85, "style": "natural_cheek"},
        ),
    ]
    steps = vote_recipes(runs)
    assert [s.zone for s in steps] == ["contour", "highlighter"]  # lip is in one run only
    assert [s.order for s in steps] == [1, 2]
    contour, highlighter = steps
    assert contour.style == "jawline" and contour.votes == 3
    assert contour.start_seconds == 32 and contour.intensity == 0.7
    # Three different highlighter styles: no majority, so no style is guessed.
    assert highlighter.style is None


def test_a_style_that_does_not_belong_to_the_zone_is_dropped_not_remapped() -> None:
    step = draft({"zone": "highlighter", "style": "jawline"}).steps[0]
    assert step.style is None
    assert draft({"zone": "lip", "style": "natural_cheek"}).steps[0].style is None
    assert draft({"zone": "eyeliner", "style": "cat_wing"}).steps[0].style == "cat_wing"
    assert draft({"zone": "lip", "style": "overlip"}).steps[0].style == "overlip"


def test_geometry_translates_each_zone_style() -> None:
    from app.schemas.look_recipe import VotedStep, geometry_for_style
    from app.services.look_recipe_service import LookRecipeService

    assert geometry_for_style("eyeliner", "cat_wing")["length"] == 0.3
    assert geometry_for_style("blush", "apple") == {"blushPlacement": "apple"}
    assert geometry_for_style("eyeshadow", "shimmer") == {"shadowFinish": "shimmer"}
    assert geometry_for_style("lip", "overlip")["overlip"] == 0.03
    assert geometry_for_style("highlighter", "nose_tip", 0.4) == {
        "hlStyle": "nose_tip",
        "intensity": 0.4,
    }
    assert geometry_for_style("contour", "jawline") == {"contourStyle": "jawline"}
    assert geometry_for_style("mascara", "slim") == {
        "length": 1.28,
        "thickness": 0.78,
        "lower": True,
    }
    assert geometry_for_style("foundation", None, 0.5) == {}
    assert (
        LookRecipeService.geometry_for(
            VotedStep(order=1, zone="eyeliner", style="puppy", votes=2, runs=3)
        )["linerStyle"]
        == "puppy"
    )


def test_unknown_zone_is_rejected() -> None:
    with pytest.raises(ValueError):
        draft({"zone": "face_shape_fix"})


async def test_extract_sends_only_the_public_url_and_votes_the_runs() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["x-goog-api-key"] == "key"
        return httpx.Response(
            200, json=reply({"zone": "contour", "start_seconds": 10, "style": "nose"})
        )

    client = GeminiClient("key", "gemini-test", transport=httpx.MockTransport(handler))
    recipe = await LookRecipeService(client).extract("abc123", runs=3)
    assert len(seen) == 3
    part = seen[0]["contents"][0]["parts"][0]
    assert part == {"fileData": {"fileUri": "https://www.youtube.com/watch?v=abc123"}}
    assert recipe.review_status == "unreviewed" and recipe.model == "gemini-test"
    assert [(s.zone, s.style) for s in recipe.steps] == [("contour", "nose")]


async def test_a_reply_outside_the_schema_is_an_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=reply({"zone": "contour", "color": "red"}))

    client = GeminiClient("key", "m", transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamError):
        await LookRecipeService(client).extract("abc123", runs=1)


async def test_without_a_key_nothing_is_requested() -> None:
    client = GeminiClient(None, "m")
    assert not client.configured
    with pytest.raises(UpstreamError):
        await client.generate_json("https://example.com", "p", {})


class FakeStore:
    def __init__(self, existing: set[tuple[str, str]]) -> None:
        self.existing = existing
        self.writes: list[tuple[str, str, dict]] = []

    async def merge_geometry(self, look_id: str, zone: str, geometry: dict) -> bool:
        if (look_id, zone) not in self.existing:
            return False
        self.writes.append((look_id, zone, geometry))
        return True


def entry(**overrides) -> ReviewEntry:
    recipe = {
        "video_id": "v1",
        "model": "m",
        "runs": 3,
        "steps": [
            {"order": 1, "zone": "contour", "style": "jawline", "votes": 3, "runs": 3},
            {
                "order": 2,
                "zone": "highlighter",
                "style": "nose_tip",
                "intensity": 0.4,
                "votes": 2,
                "runs": 3,
            },
            {"order": 3, "zone": "lip", "votes": 3, "runs": 3},
        ],
    }
    return ReviewEntry.model_validate(
        {"video_id": "v1", "look_id": "LOOK-9", "recipe": recipe, **overrides}
    )


async def test_apply_writes_only_approved_named_entries_into_existing_zone_settings() -> None:
    service = LookRecipeService(None)
    store = FakeStore({("LOOK-9", "contour"), ("LOOK-9", "highlighter")})
    result = await service.apply([entry(approved=True, reviewer="jy")], store)
    assert result["applied"] == ["LOOK-9:contour", "LOOK-9:highlighter"]
    assert store.writes == [
        ("LOOK-9", "contour", {"contourStyle": "jawline"}),
        ("LOOK-9", "highlighter", {"hlStyle": "nose_tip", "intensity": 0.4}),
    ]


async def test_apply_skips_unreviewed_unnamed_and_unlinked_entries() -> None:
    service = LookRecipeService(None)
    store = FakeStore({("LOOK-9", "contour")})
    for bad in (
        entry(),  # not approved
        entry(approved=True),  # no reviewer
        entry(approved=True, reviewer="jy", look_id=None),  # no look
    ):
        assert (await service.apply([bad], store))["applied"] == []
    assert store.writes == []
    # A look without a setting for the zone is reported, and no color is made up for it.
    result = await service.apply([entry(approved=True, reviewer="jy")], store)
    assert result["applied"] == ["LOOK-9:contour"]
    assert any("highlighter" in line for line in result["skipped"])


async def test_a_busy_answer_is_retried_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}})
        return httpx.Response(200, json=reply({"zone": "lip", "start_seconds": 5}))

    client = GeminiClient(
        "key", "m", transport=httpx.MockTransport(handler), retry_delays=(0, 0, 0)
    )
    text = await client.generate_json("https://example.com", "p", {})
    assert calls["n"] == 3 and "lip" in text


async def test_a_permanent_error_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, json={"error": {"status": "NOT_FOUND"}})

    client = GeminiClient("key", "m", transport=httpx.MockTransport(handler), retry_delays=(0, 0))
    with pytest.raises(UpstreamError):
        await client.generate_json("https://example.com", "p", {})
    assert calls["n"] == 1
