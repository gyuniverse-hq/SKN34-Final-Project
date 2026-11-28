"""Real matching/parent execution with synthetic Catalog/model inputs."""

import pytest

from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.consultation_parent import ConsultationParent, ParentTask
from app.schemas.consultation_task import (
    ConsultationTaskRequest,
    ProductRequirement,
    ProductRequirementChange,
)
from app.schemas.supervisor import SearchPlan
from app.services.beauty_consultation_service import execute_beauty
from app.services.consultation_parent_graph import execute_request
from app.services.product_search_contract import catalog_kind, resolve_requirement
from tests.test_beauty_consultation import Catalog, product


@pytest.fixture
def anyio_backend():
    return "asyncio"


def named(name, price=15000):
    return product(name, price, category="skincare")


@pytest.mark.parametrize(
    "name,kind",
    [
        ("보습 장벽 크림", "cream"),
        ("클렌징크림", "cleansing_cream"),
        ("선크림", "sunscreen"),
        ("톤업 크림", "tone_up_cream"),
        ("아이크림", "eye_cream"),
        ("수면크림팩", "mask"),
        ("[크림 증정] 수분 토너", "toner"),
        ("[장벽토너] 보습 로션", None),
        ("토너 크림 세트", None),
        ("이름 없는 제품", None),
    ],
)
def test_catalog_identity_not_generic_cream_substring(name, kind):
    assert catalog_kind(named(name)) == kind


def test_delta_preserves_changes_and_requires_grounded_release():
    previous = ProductRequirement(kind="cream")
    assert (
        resolve_requirement(previous, ProductRequirementChange(operation="keep"), "예산 변경")[0]
        == previous
    )
    assert resolve_requirement(previous, None, "예산 변경", required=True) == (previous, True)
    assert resolve_requirement(
        previous, ProductRequirementChange(operation="clear", quote="거짓"), "예산 변경"
    )[1]
    assert (
        resolve_requirement(
            previous, ProductRequirementChange(operation="clear", quote="종류 해제"), "종류 해제"
        )[0].kind
        is None
    )
    assert (
        resolve_requirement(
            previous, ProductRequirementChange(operation="set", kind="lotion", quote="로션"), "로션"
        )[0].kind
        == "lotion"
    )


@pytest.mark.parametrize("operation", ["keep", "set", "clear"])
def test_null_optional_quote_never_authorizes_a_kind_change(operation):
    previous = ProductRequirement(kind="cream")
    plan = SearchPlan.model_validate(
        {
            "intent": "refine",
            "scope": "catalog",
            "productRequirement": {"operation": operation, "kind": "lotion", "quote": None},
        }
    )
    assert resolve_requirement(previous, plan.product_requirement, "예산 변경") == (
        previous,
        operation != "keep",
    )


@pytest.mark.anyio
async def test_real_filter_parent_completion_and_unknown_are_distinct():
    catalog = Catalog()
    catalog.products = [
        named("수분 토너"),
        named("클렌징크림"),
        named("보습 크림"),
        named("종류 불명"),
    ]
    req = ChatRequest(message="보습 크림", locale="ko")
    req._product_contract_required = True
    plan = SearchPlan(
        intent="search",
        category="skincare",
        moisturizing=True,
        product_requirement=ProductRequirementChange(operation="set", kind="cream", quote="크림"),
    )
    response = await execute_beauty(req, plan, catalog)
    assert [p.id for p in response.products] == ["보습 크림"]
    assert response._product_assessment.status == "completed"
    parent = ConsultationParent(tasks=[ParentTask(goal="product", version=1)])
    task = parent.tasks[0]

    async def operation():
        return response

    await execute_request(
        parent,
        task,
        ConsultationTaskRequest(task_id="product", capability="product", inputs={}),
        operation,
    )
    assert task.product_requirement.kind == "cream" and task.status == "completed"
    assert task.product_context["filters"]["moisturizing"]
    catalog.products = [named("종류 불명")]
    response = await execute_beauty(req, plan, catalog)
    assert not response.products and response._product_assessment.outcome == "unknown"
    await execute_request(
        parent,
        task,
        ConsultationTaskRequest(task_id="product", capability="product", inputs={}),
        operation,
    )
    assert task.status == "partial"
    catalog.products = [named("수분 토너")]
    response = await execute_beauty(req, plan, catalog)
    assert response._product_assessment.status == "completed"
    assert response._product_assessment.outcome == "no_match"


@pytest.mark.anyio
async def test_unassessed_product_response_cannot_be_completed():
    parent = ConsultationParent(tasks=[ParentTask(goal="product", version=1)])

    async def operation():
        return ChatResponse(answer="상품을 찾았어요", products=[])

    await execute_request(
        parent,
        parent.tasks[0],
        ConsultationTaskRequest(task_id="product", capability="product", inputs={}),
        operation,
    )
    assert parent.tasks[0].status == "partial"


def test_adapter_rejects_completed_kind_without_matching_product_evidence():
    from app.schemas.consultation_task import ProductAssessment
    from app.services.consultation_task_adapter import adapt_independent, validate_results

    parent = ConsultationParent(tasks=[ParentTask(goal="product", version=1, status="completed")])
    task = parent.tasks[0]
    task.product_assessment = ProductAssessment(
        status="completed",
        outcome="matched",
        requirement=ProductRequirement(kind="cream"),
        matched=1,
    )
    payload = ChatResponse(
        answer="상품", products=[{"id": "p1", "brand": "b", "name": "n", "category": "skincare"}]
    )
    with pytest.raises(ValueError, match="Unverified product kind"):
        validate_results([adapt_independent(parent, task, payload, {})])


@pytest.mark.anyio
async def test_failed_reread_discards_old_assessment_but_keeps_requirement():
    from app.core.errors import UpstreamError
    from app.schemas.consultation_task import ProductAssessment
    from app.services.consultation_task_adapter import adapt_independent, validate_results

    requirement = ProductRequirement(kind="cream")
    parent = ConsultationParent(
        tasks=[
            ParentTask(
                goal="product",
                version=1,
                product_requirement=requirement,
                product_assessment=ProductAssessment(
                    status="completed", outcome="matched", requirement=requirement, matched=1
                ),
            )
        ]
    )

    async def unavailable():
        raise UpstreamError("synthetic catalog failure")

    task = parent.tasks[0]
    await execute_request(
        parent,
        task,
        ConsultationTaskRequest(task_id="product", capability="product", inputs={}),
        unavailable,
    )
    assert task.status == "failed" and task.product_assessment is None
    assert task.product_requirement == requirement
    assert validate_results([adapt_independent(parent, task, None, {})])[0].status == "failed"


@pytest.mark.anyio
async def test_delegated_search_metadata_keeps_original_utterance():
    import json

    from app.services.beauty_consultation_service import interpret_beauty
    from tests.test_beauty_consultation import PlanLlm

    req = ChatRequest(message="크림도 찾아줘", locale="ko")
    req._product_contract_required = True
    req._product_operation = "search"
    model = PlanLlm(
        intent="search",
        scope="catalog",
        category="skincare",
        productRequirement={"operation": "set", "kind": "cream", "quote": "크림"},
    )
    await interpret_beauty(req, model)
    payload = json.loads(model.messages[-1]["content"])
    assert payload["parentTask"] == {"operation": "search", "hasPriorContext": False}
    assert req.message in model.messages[-1]["content"]
    assert req.screen_context is None


@pytest.mark.anyio
@pytest.mark.parametrize("option_hint", [True, False])
async def test_kind_and_ingredient_conditions_bind_option_query_and_assessment(
    monkeypatch, option_hint
):
    from app.core.config import get_settings
    from app.schemas.catalog import CheckedScope, OptionCandidate, OptionCheck, OptionSearchResponse

    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)

    class Options:
        def __init__(self):
            self.calls = []

        async def search_options(self, request):
            self.calls.append(request)
            products = [named("보습 크림"), named("클렌징크림"), named("종류 불명")]
            return OptionSearchResponse(
                status="SUCCESS",
                products=products,
                items=[
                    OptionCandidate(
                        productId=p.id,
                        shadeId=None,
                        optionId=p.id + "-sale",
                        sourceVersion="synthetic",
                        group="ELIGIBLE",
                        checks=[
                            OptionCheck(condition="ingredient", verdict="MATCH", reason="synthetic")
                        ],
                    )
                    for p in products
                ],
                excludedCount=0,
                omittedCount=0,
                checkedScope=CheckedScope(
                    candidateProducts=3,
                    candidateOptions=3,
                    checkedOptions=3,
                    unidentifiedOptions=0,
                    exhaustive=True,
                    stoppedReason="COMPLETE",
                    errors=0,
                ),
            )

    c = Options()
    req = ChatRequest(message="향료 제외 크림 찾아줘", locale="ko")
    req._product_contract_required = True
    plan = SearchPlan(
        intent="search",
        category="skincare",
        optionSearch=option_hint,
        ingredientConditions=[{"ingredientName": "향료", "operator": "excludes"}],
        productRequirement={"operation": "set", "kind": "cream", "quote": "크림"},
    )
    r = await execute_beauty(req, plan, c)
    assert (
        c.calls[-1].query == "크림"
        and c.calls[-1].ingredient_conditions[0].ingredient_name == "향료"
    )
    assert [p.id for p in r.products] == ["보습 크림"]
    assert {i.product_id: i.group for i in r.option_search.items} == {
        "보습 크림": "ELIGIBLE",
        "클렌징크림": "EXCLUDED",
        "종류 불명": "REFERENCE_ONLY",
    }
    assert (
        r._product_assessment.status == "partial"
        and r._product_assessment.requirement.kind == "cream"
    )
    assert r.option_search.checked_scope.checked_options == 3
    assert not r.chat_context.filters.query
    req.chat_context = r.chat_context
    req.message = "예산만 2만원으로 바꿔줘"
    budget = SearchPlan(
        intent="refine",
        scope="previous",
        maxPriceKRW=20000,
        productRequirement={"operation": "keep"},
    )
    await execute_beauty(req, budget, c)
    assert c.calls[-1].query == "크림" and c.calls[-1].max_price_krw == 20000
    assert c.calls[-1].ingredient_conditions[0].ingredient_name == "향료"
    clear = SearchPlan(
        intent="refine",
        scope="previous",
        clearFilters=["ingredientConditions"],
        productRequirement={"operation": "keep"},
    )
    req.message = "성분 조건 빼줘"
    await execute_beauty(req, clear, c)
    assert not c.calls[-1].ingredient_conditions and c.calls[-1].query == "크림"


@pytest.mark.parametrize("term", ["립펜슬", "아이브로우 펜슬"])
def test_explicit_catalog_name_type_is_grounded_and_survives_budget_change(term):
    from app.services.product_search_contract import inspect_candidates

    message = f"{term} 찾아줘"
    requirement, unresolved = resolve_requirement(
        None,
        ProductRequirementChange(operation="set", name_term=term, quote=message),
        message,
        required=True,
    )
    assert not unresolved and requirement.name_term == term and requirement.kind is None
    kept, unresolved = resolve_requirement(
        requirement, ProductRequirementChange(operation="keep"), "예산만 2만원", required=True
    )
    assert kept == requirement and not unresolved
    accepted, assessment, evidence = inspect_candidates(
        [named(f"브랜드 {term} 01"), named("브랜드 립스틱 01")], kept
    )
    assert [p.name for p in accepted] == [f"브랜드 {term} 01"]
    assert assessment.matched == 1 and assessment.unknown == 0
    assert list(evidence.values())[0]["nameTerm"] == term
    assert (
        resolve_requirement(
            kept, ProductRequirementChange(operation="clear", quote="종류 해제"), "종류 해제"
        )[0]
        == ProductRequirement()
    )
    assert resolve_requirement(
        kept, ProductRequirementChange(operation="set", name_term="추측", quote=message), message
    )[1]


def test_name_type_anchors_to_delegated_clause_even_with_outer_quote():
    change = ProductRequirementChange(
        operation="set", name_term="립펜슬", quote="립펜슬 찾아줘. 피부 상담은 유지해줘."
    )
    assert resolve_requirement(None, change, "립펜슬 찾아줘", required=True) == (
        ProductRequirement(name_term="립펜슬"),
        False,
    )
    previous = ProductRequirement(kind="cream")
    assert resolve_requirement(previous, change, "예산만 변경해줘", required=True) == (
        previous,
        True,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("expired", [False, True])
async def test_explicit_makeup_kind_executes_catalog_and_filters_real_return_values(
    monkeypatch, expired
):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)

    class NamedCatalog(Catalog):
        async def search_products(self, **kwargs):
            self.search_call = kwargs
            return [
                product("브랜드 립펜슬 01", 10000, category="lip"),
                product("브랜드 립스틱 02", 12000, category="lip"),
            ]

    catalog = NamedCatalog()
    req = ChatRequest(message="별도로 립펜슬 찾아줘", locale="ko")
    req._product_contract_required = True
    req._product_operation = "search"
    if expired:
        from app.schemas.chat import BeautyContext, BeautyFilters

        req.chat_context = BeautyContext(
            filters=BeautyFilters(category="lip", max_price_krw=11000),
            candidate_ids=["expired-candidate"],
            issued_at=1,
        )
    plan = SearchPlan(
        intent="search",
        category="lip",
        scope="catalog",
        productRequirement={"operation": "set", "name_term": "립펜슬", "quote": "립펜슬 찾아줘"},
    )
    result = await execute_beauty(req, plan, catalog, g1=True)
    assert catalog.search_call["category"] == "lip"
    assert [p.name for p in result.products] == ["브랜드 립펜슬 01"]
    assert result._product_assessment.requirement.name_term == "립펜슬"
    assert result._product_assessment.outcome == "matched"
    assert "상품 종류를 확인" not in result.answer
    if expired:
        assert result.chat_context.filters.max_price_krw == 11000
        assert "expired-candidate" not in result.chat_context.candidate_ids
