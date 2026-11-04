"""Synthetic legacy API responses exercise the production client and public projection."""

import httpx
import pytest

from app.clients.catalog_client import CatalogClient, IngredientLookupError
from app.schemas.catalog import CatalogIngredients
from app.services.beauty_consultation_service import _combine_ingredient_results
from app.services.chat_service import ChatService
from tests.test_beauty_consultation import PlanLlm
from tests.test_ingredient_consultation import (
    IngredientsCatalog,
    context,
    evidence,
    install_http,
    request,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("operator", ["includes", "excludes"])
@pytest.mark.parametrize(
    "source,query",
    [
        ("레티놀", "retinol"),
        ("Retinol", "レチノール"),
        ("视黄醇", "retinol"),
        ("Panthenol", "Provitamin B5"),
    ],
)
async def test_legacy_absence_is_downgraded_without_discarding_reviewed_list(
    monkeypatch, operator, source, query
):
    payload = evidence(name=query, operator=operator, ingredients=[dict(name=source, sequence=1)])
    install_http(monkeypatch, lambda req: httpx.Response(200, json=payload))
    result = await CatalogClient("http://catalog.test").get_ingredients(
        "a", "a-03", ingredient_name=query, operator=operator
    )
    assert result.status == "ok" and result.verified and result.complete
    assert result.verdict == "UNKNOWN" and result.reason == "ingredient_identity_unresolved"
    assert result.ingredients[0].name == source
    assert result.conditions[0].verdict == result.verdict
    assert result.conditions[0].reason == result.reason


@pytest.mark.anyio
@pytest.mark.parametrize(
    "locale,notice", [("ko", "미확인"), ("en", "unverified"), ("ja", "未確認"), ("zh", "未确认")]
)
@pytest.mark.parametrize("operator", ["includes", "excludes"])
async def test_unresolved_condition_is_visible_and_not_success(
    monkeypatch, locale, notice, operator
):
    install_http(
        monkeypatch,
        lambda req: httpx.Response(200, json=evidence(name="retinol", operator=operator)),
    )
    catalog = IngredientsCatalog(CatalogClient("http://catalog.test"))
    result = await ChatService(
        None,
        PlanLlm(
            intent="detail",
            ingredientLookup=True,
            ingredientName="retinol",
            ingredientOperator=operator,
        ),
        catalog,
    ).answer(request(context(), locale))
    public = result.model_dump(mode="json", by_alias=True)
    assert result.result_type == "clarification"
    assert result.tool_result.status == "clarification"
    assert notice in public["answer"] and "retinol" in public["answer"]
    assert public["ingredientResults"][0]["verdict"] == "UNKNOWN"
    assert (
        public["ingredientResults"][0]["conditions"][0]["reason"]
        == "ingredient_identity_unresolved"
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "bad", ["product", "option", "evidence", "synthetic", "contradiction", "missing_condition"]
)
async def test_malformed_absence_remains_error(monkeypatch, bad):
    payload = evidence(name="retinol", operator="excludes")
    if bad == "product":
        payload["productId"] = "foreign"
    elif bad == "option":
        payload["conditions"][0]["optionId"] = "foreign"
    elif bad == "evidence":
        payload["conditions"][0]["evidenceId"] = "foreign"
    elif bad == "synthetic":
        payload["conditions"][0]["synthetic"] = False
    elif bad == "contradiction":
        payload["ingredients"] = [dict(name="retinol", sequence=1)]
    else:
        payload["conditions"] = []
    install_http(monkeypatch, lambda req: httpx.Response(200, json=payload))
    with pytest.raises(IngredientLookupError) as error:
        await CatalogClient("http://catalog.test").get_ingredients(
            "a", "a-03", ingredient_name="retinol", operator="excludes"
        )
    assert error.value.reason == "invalid_response"


@pytest.mark.anyio
async def test_unconditional_reviewed_list_still_succeeds(monkeypatch):
    install_http(monkeypatch, lambda req: httpx.Response(200, json=evidence()))
    result = await ChatService(
        None,
        PlanLlm(intent="detail", ingredientLookup=True),
        IngredientsCatalog(CatalogClient("http://catalog.test")),
    ).answer(request(context(), "en"))
    assert result.result_type == "product_detail" and result.tool_result.status == "success"
    assert "Verified ingredient list" in result.answer


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "other,expected", [("MATCH", "UNKNOWN"), ("NOT_MATCH", "NOT_MATCH"), ("ERROR", "ERROR")]
)
def test_aggregate_preserves_unknown_reason_and_other_verdict(reverse, other, expected):
    unknown = CatalogIngredients.model_validate(
        evidence(name="retinol", verdict="UNKNOWN", reason="ingredient_identity_unresolved")
    )
    decisive = CatalogIngredients.model_validate(
        evidence(
            name="향료",
            verdict=other,
            operator="excludes" if other == "NOT_MATCH" else "includes",
            reason="source_unavailable" if other == "ERROR" else "ingredient_present",
            status="error" if other == "ERROR" else "ok",
        )
    )
    results = [unknown, decisive]
    combined = _combine_ingredient_results(list(reversed(results)) if reverse else results)
    assert combined.verdict == expected
    assert any(
        c.verdict == "UNKNOWN" and c.reason == "ingredient_identity_unresolved"
        for c in combined.conditions
    )
    if expected == "UNKNOWN":
        assert combined.reason == "ingredient_identity_unresolved"


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "field",
    ["evidence_id", "source_version", "source_fingerprint", "generator_version", "ingredients"],
)
def test_conditions_from_different_snapshots_do_not_become_verified(reverse, field):
    unknown = CatalogIngredients.model_validate(
        evidence(name="retinol", verdict="UNKNOWN", reason="ingredient_identity_unresolved")
    )
    other = CatalogIngredients.model_validate(evidence(name="향료", verdict="MATCH"))
    if field == "ingredients":
        other.ingredients[0].name = "different snapshot ingredient"
    else:
        setattr(other, field, "different-snapshot")
    rows = [unknown, other]
    combined = _combine_ingredient_results(list(reversed(rows)) if reverse else rows)
    assert combined.verdict == "UNKNOWN" and combined.reason == "evidence_requires_review"
    assert not combined.verified and not combined.ingredients


@pytest.mark.parametrize("reverse", [False, True])
def test_error_verdict_survives_even_when_lookup_status_is_ok(reverse):
    unknown = CatalogIngredients.model_validate(
        evidence(name="retinol", verdict="UNKNOWN", reason="ingredient_identity_unresolved")
    )
    failed = CatalogIngredients.model_validate(
        evidence(name="향료", verdict="ERROR", reason="source_unavailable")
    )
    rows = [unknown, failed]
    combined = _combine_ingredient_results(list(reversed(rows)) if reverse else rows)
    assert combined.status == "error" and combined.verdict == "ERROR"
    assert combined.reason == "source_unavailable"


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "field", ["ingredient_coverage", "normalization_status", "source", "collected_at"]
)
def test_condition_order_cannot_upgrade_partial_or_conflicting_metadata(reverse, field):
    first = CatalogIngredients.model_validate(evidence(name="향료"))
    other = first.model_copy(deep=True)
    changes = {
        "ingredient_coverage": "partial",
        "normalization_status": "unverified",
        "source": "fixture://another-source",
        "collected_at": first.collected_at.replace(year=2025),
    }
    setattr(other, field, changes[field])
    rows = [first, other]
    combined = _combine_ingredient_results(list(reversed(rows)) if reverse else rows)
    assert combined.verdict == "UNKNOWN" and combined.reason == "evidence_requires_review"
    assert not combined.verified and not combined.complete
