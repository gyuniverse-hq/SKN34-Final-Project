"""Synthetic HTTP identity proof and multiple constraints; no paid calls or DB."""

import httpx
import pytest
from pydantic import ValidationError

from app.clients.catalog_client import CatalogClient, IngredientLookupError
from app.core.errors import ApiError
from app.repositories.chat_session_repository import ChatSessionRepository
from app.schemas.catalog import IngredientIdentity
from app.schemas.supervisor import SearchPlan
from app.services.beauty_consultation_service import execute_beauty
from app.services.chat_service import ChatService
from tests.test_beauty_consultation import PlanLlm
from tests.test_chat_sessions import RedisDouble
from tests.test_ingredient_consultation import evidence, install_http
from tests.test_ingredient_search_coverage import SearchCatalog, search_request


@pytest.fixture
def anyio_backend():
    return "asyncio"


def identity(number):
    return dict(
        mfdsIngredientId=number,
        nameKo=f"official-{number}",
        sourceHash="a" * 64,
        matchMethod="exact_name",
        ruleVersion="fixture-v1",
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "present,operator,verdict",
    [
        (True, "includes", "MATCH"),
        (True, "excludes", "NOT_MATCH"),
        (False, "includes", "NOT_MATCH"),
        (False, "excludes", "MATCH"),
    ],
)
async def test_client_recomputes_canonical_presence_and_absence(
    monkeypatch, present, operator, verdict
):
    body = evidence(
        name="official alias",
        operator=operator,
        verdict=verdict,
        ingredients=[dict(name="Original label", sequence=1, identity=identity(73))],
    )
    body["conditions"][0]["queryIdentity"] = identity(73 if present else 29)
    install_http(monkeypatch, lambda req: httpx.Response(200, json=body))
    result = await CatalogClient("http://fixture.test").get_ingredients(
        "a", "a-03", ingredient_name="official alias", operator=operator
    )
    assert result.verdict == verdict and result.ingredients[0].name == "Original label"


@pytest.mark.anyio
async def test_one_unmapped_entry_blocks_canonical_absence(monkeypatch):
    body = evidence(
        name="absent",
        operator="excludes",
        verdict="MATCH",
        ingredients=[
            dict(name="Original", sequence=1, identity=identity(73)),
            dict(name="Unresolved", sequence=2),
        ],
    )
    body["conditions"][0]["queryIdentity"] = identity(29)
    install_http(monkeypatch, lambda req: httpx.Response(200, json=body))
    result = await CatalogClient("http://fixture.test").get_ingredients(
        "a", "a-03", ingredient_name="absent", operator="excludes"
    )
    assert result.verdict == "UNKNOWN" and result.conditions[0].verdict == "UNKNOWN"


@pytest.mark.anyio
async def test_forged_identity_provenance_is_rejected(monkeypatch):
    body = evidence(
        name="alias",
        verdict="MATCH",
        ingredients=[dict(name="Original", sequence=1, identity=identity(73))],
    )
    body["conditions"][0]["queryIdentity"] = {
        **identity(73),
        "matchMethod": "manual",
        "ruleVersion": None,
    }
    install_http(monkeypatch, lambda req: httpx.Response(200, json=body))
    with pytest.raises(IngredientLookupError, match="invalid_response"):
        await CatalogClient("http://fixture.test").get_ingredients(
            "a", "a-03", ingredient_name="alias"
        )


@pytest.mark.anyio
async def test_colorless_client_omits_shade_query_parameter(monkeypatch):
    def handler(req):
        assert "shadeId" not in req.url.params
        return httpx.Response(
            200,
            json=evidence(
                shade=None,
                name="Water",
                verdict="MATCH",
                ingredients=[dict(name="Water", sequence=1)],
            ),
        )

    install_http(monkeypatch, handler)
    assert (
        await CatalogClient("http://fixture.test").get_ingredients(
            "a", None, ingredient_name="Water"
        )
    ).verdict == "MATCH"


@pytest.mark.anyio
@pytest.mark.parametrize("reverse", [True, False])
async def test_one_utterance_multiple_conditions_and_followup_preserve_constraints(reverse):
    catalog = SearchCatalog(3, reverse=reverse)
    # Different IDs and terms than the API fixtures; order must not affect selection.
    for index, p in enumerate(catalog.products):
        p.id = f"independent-{index}"
        p.shades = []
        p.category = "skincare"
    catalog.ingredients = {
        "independent-0": ["Bisabolol"],
        "independent-1": ["Bisabolol", "Menthol"],
        "independent-2": ["Water"],
    }
    plan = SearchPlan(
        intent="search",
        category="skincare",
        maxPriceKRW=18000,
        ingredientConditions=[
            dict(ingredientName="Bisabolol", operator="includes"),
            dict(ingredientName="Menthol", operator="excludes"),
        ],
    )
    response = await execute_beauty(search_request(), plan, catalog)
    assert [p.id for p in response.products] == ["independent-0"]
    assert len(response.ingredient_results[0].conditions) == 2
    assert response.chat_context.shade_selections == {}
    # This direct catalog double uses synthetic verdicts; HTTP canonical proof is tested above.
    followup = await execute_beauty(
        search_request(response.chat_context),
        SearchPlan(intent="refine", scope="previous", maxPriceKRW=16000),
        catalog,
    )
    assert len(followup.chat_context.filters.ingredient_conditions) == 2
    assert [p.id for p in followup.products] == ["independent-0"]


@pytest.mark.anyio
async def test_colorless_verified_evidence_round_trips_through_session_storage():
    catalog = SearchCatalog(1, matches=[0])
    catalog.products[0].shades = []
    catalog.products[0].category = "skincare"
    llm = PlanLlm(intent="search", category="skincare", ingredientName="Niacinamide")
    repo = ChatSessionRepository(RedisDouble())
    service = ChatService(None, llm, catalog, sessions=repo)
    owner = "guest:colorless-session"
    response = await service.answer(search_request(), owner)
    assert response.session_status == "stored" and response.ingredient_results[0].verified
    stored = await repo.load(owner, response.chat_context.session)
    assert stored.evidence_refs[0]["shadeId"] is None
    llm.plan = dict(intent="detail", scope="previous", ordinal=1, ingredientName="Niacinamide")
    followup = await service.answer(search_request(response.chat_context), owner)
    assert followup.session_status == "stored" and followup.ingredient_results[0].verdict == "MATCH"


@pytest.mark.parametrize(
    "method,changes",
    [
        ("exact_name", {"ruleVersion": "  "}),
        ("manual", {"reviewedBy": "  ", "reviewedAt": "2026-01-01T00:00:00Z"}),
    ],
)
def test_whitespace_cannot_establish_identity_provenance(method, changes):
    with pytest.raises(ValidationError):
        IngredientIdentity.model_validate({**identity(73), "matchMethod": method, **changes})


@pytest.mark.anyio
async def test_detail_merges_legacy_and_list_constraints_instead_of_dropping_one():
    catalog = SearchCatalog(1, matches=[0])
    catalog.products[0].shades = []
    catalog.products[0].category = "skincare"
    first = await execute_beauty(
        search_request(), SearchPlan(intent="search", category="skincare"), catalog
    )
    result = await execute_beauty(
        search_request(first.chat_context),
        SearchPlan(
            intent="detail",
            ordinal=1,
            ingredientName="Niacinamide",
            ingredientConditions=[
                dict(ingredientName="Menthol", operator="excludes"),
            ],
        ),
        catalog,
    )
    assert {c.ingredient_name for c in result.ingredient_results[0].conditions} == {
        "Niacinamide",
        "Menthol",
    }


@pytest.mark.anyio
async def test_conflicting_same_utterance_conditions_are_not_silently_replaced():
    plan = SearchPlan(
        intent="search",
        category="skincare",
        ingredientName="Niacinamide",
        ingredientConditions=[dict(ingredientName="Niacinamide", operator="excludes")],
    )
    with pytest.raises(ApiError) as exc:
        await execute_beauty(search_request(), plan, SearchCatalog(1))
    assert exc.value.code == "conflicting_ingredient_conditions"



@pytest.mark.anyio
async def test_fragrance_and_ingredient_constraints_exclude_known_mismatches():
    # Fragrance-free is still UNKNOWN; a proven ingredient failure must not
    # appear as a candidate or consume a slot ahead of later matches.
    catalog = SearchCatalog(3, matches=[2])
    catalog.states = {"item-001": "UNKNOWN"}
    plan = SearchPlan(
        intent="search",
        category="lip",
        shadeName="03",
        fragranceFree=True,
        ingredientConditions=[dict(ingredientName="Niacinamide", operator="includes")],
    )
    response = await execute_beauty(search_request(), plan, catalog)
    assert [product.id for product in response.products] == ["item-001", "item-002"]
    assert [result.verdict for result in response.ingredient_results] == ["UNKNOWN", "MATCH"]
    assert response.chat_context.candidate_ids == ["item-001", "item-002"]
    assert response.result_type == "clarification"
    assert response.chat_context.filters.fragrance_free
