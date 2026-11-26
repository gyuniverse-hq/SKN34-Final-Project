"""Read-only N02 first connection: exact recipe matches, not inferred substitutions."""

import hashlib
import json
import re
from uuid import uuid4

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.schemas.catalog import OptionSearchRequest
from app.schemas.chat import ChatResponse, ProductRef
from app.schemas.owned_look_consultation import (
    OwnedLookBinding,
    OwnedLookCoverage,
    OwnedLookProduct,
    OwnedLookResult,
    OwnedLookTask,
)
from app.schemas.owned_look_context import OwnedLookContext, OwnershipDeclaration
from app.services.consultation_memory import (
    CONSULTATION_MEMORY_LIMIT,
    ignores_memory,
    verified_inventory_matches,
)
from app.services.g1_catalog_tool import validate_catalog_product
from app.services.owned_look_filters import filter_followup, has_filters, update_filters
from app.services.style_recipe_service import NAMES, ORDER, execute_style

_OWNED = re.compile(r"보유|(?:내가|제가|이미)\s*가진|갖고\s*있는|가지고\s*있는")
_STATE_REQUEST = re.compile(
    r"발라|적용해|설정해|조절해|기억해|저장해|삭제해|장바구니|\bAR\b|가상\s*메이크업", re.I
)
_ZONE_TERMS = {
    "foundation": r"베이스|파운데이션|쿠션",
    "brow": r"눈썹|브로우",
    "eyeshadow": r"아이섀도|아이섀도우",
    "eyeliner": r"아이라이너|아이라인",
    "mascara": r"마스카라",
    "blush": r"블러셔|볼터치",
    "contour": r"윤곽|쉐딩",
    "highlighter": r"하이라이터",
    "lip": r"립|틴트|립스틱",
}


def may_consult_owned_look(req):
    """Candidate only; parent must resolve mixed/AR/memory execution routing first.

    This first slice conservatively declines state verbs, including ambiguous ones.
    A lexical match never grants consent or overrides the parent's semantic scope.
    """
    return bool(
        get_settings().g8_enabled
        and req.locale == "ko"
        and req.request_type in {"chat", "beauty_consultation"}
        and not (req.ar_context or req.screen_context or req.style_search)
        and not _STATE_REQUEST.search(req.message)
        and (
            (
                _OWNED.search(req.message)
                and re.search(r"룩|스타일|따라", req.message)
                and re.search(r"추천|추가|필요|부족", req.message)
            )
            or (
                req._owned_look_context is not None
                and req.style_context is not None
                and (req.style_context.kind, req.style_context.look_id)
                == (req._owned_look_context.kind, req._owned_look_context.look_id)
                and (
                    declaration_updates(req.message)[0]
                    or declaration_updates(req.message)[1]
                    or filter_followup(req.message)
                    or re.fullmatch(
                        r"(?:그럼\s*)?(?:다시\s*)?추천해\s*줘[.!]?", req.message.strip()
                    )
                )
            )
        )
    )


def declaration_updates(message):
    """Only explicit self declarations and scoped condition releases; no state execution."""
    if re.search(r"친구|엄마|동생|언니|누나|타인|다른\s*사람|기억|장바구니|\bAR\b", message):
        return {}, False
    updates = {}
    clear_all = False
    for clause in re.split(r"[.!\n]", message):
        if "?" in clause or re.search(r"(?:라고|다는|다고)\s*(?:말|했|하|기억)", clause):
            continue
        if re.fullmatch(
            r"\s*(?:전체\s*|모든\s*)?미보유\s*조건(?:을|은)?\s*(?:전부\s*)?(?:해제|취소)해\s*줘\s*",
            clause,
        ):
            updates.clear()
            clear_all = True
            continue
        for zone, terms in _ZONE_TERMS.items():
            release = re.search(
                rf"(?:{terms})(?:의)?\s*(?:미보유|보유)?\s*조건(?:을|은)?\s*(?:해제|취소)해\s*줘",
                clause,
            )
            if release:
                updates[zone] = None
                continue
            match = re.search(
                rf"(?:{terms})(?:은|는|이|가)?\s*(?:이제\s*)?(?P<state>없|있)"
                r"(?:어요|습니다|어|다)(?=$|\s|[,])",
                clause,
            )
            if match:
                updates[zone] = OwnershipDeclaration(
                    status="missing" if match["state"] == "없" else "present",
                    quote=match.group(0),
                )
    return updates, clear_all


def _exact_links(recipe, zone):
    return [
        link
        for link in recipe.products
        if link.zone == zone
        and link.catalog_valid
        and link.mapping_status == "verified"
        and link.product_id
        and link.shade_id
    ]


def next_context(req, recipe_version):
    previous = req._owned_look_context
    same_look = previous is not None and (previous.kind, previous.look_id) == (
        req.style_context.kind,
        req.style_context.look_id,
    )
    same_recipe = previous is not None and (
        previous.kind,
        previous.look_id,
        previous.recipe_version,
    ) == (req.style_context.kind, req.style_context.look_id, recipe_version)
    declarations = dict(previous.declarations) if same_recipe else {}
    updates, clear_all = declaration_updates(req.message)
    if clear_all:
        declarations.clear()
    for zone, declaration in updates.items():
        if declaration is None:
            declarations.pop(zone, None)
        else:
            declarations[zone] = declaration
    return OwnedLookContext(
        kind=req.style_context.kind,
        look_id=req.style_context.look_id,
        recipe_version=recipe_version,
        version=previous.version + 1 if same_recipe else 1,
        declarations=declarations,
        filters=update_filters(previous.filters if same_look else None, req.message),
    )


async def execute_owned_look(req, catalog, *, trace=None):
    """Called by the parent after routing. G7 owns permission, version fences and storage."""
    if not may_consult_owned_look(req):
        return None
    if (
        not req.structured_memory
        or req._g7_execution is None
        or req._consultation_memories is None
        or ignores_memory(req.message)
    ):
        return ChatResponse(
            answer="동의하고 저장한 보유 제품을 확인할 수 있는 상담에서 이어 주세요.",
            products=[],
            result_type="clarification",
        )
    if req.style_context is None:
        return ChatResponse(
            answer="먼저 따라 해 볼 룩을 선택해 주세요.", products=[], result_type="clarification"
        )
    if catalog is None:
        response = ChatResponse(
            answer="상품 자료를 조회하지 못했어요. 잠시 후 다시 시도해 주세요.", products=[]
        )
        if req._owned_look_context is not None:
            response._owned_look_context = next_context(req, req._owned_look_context.recipe_version)
        return response

    plan_id = uuid4()
    results = {}

    def record(task_id, agent, inputs, *, bindings=(), **output):
        links = [
            OwnedLookBinding(source_task=t, source_field=f, target_input=f) for t, f in bindings
        ]
        task = OwnedLookTask(
            task_id=task_id,
            plan_id=plan_id,
            agent=agent,
            depends_on=list(dict.fromkeys(t for t, _ in bindings)),
            input_bindings=links,
        )
        for binding in links:
            source = results[binding.source_task]
            if source.plan_id != plan_id or source.plan_version != task.plan_version:
                raise ValueError("Different owned-look plan")
            if inputs[binding.target_input] != getattr(source, binding.source_field):
                raise ValueError("Owned-look data binding mismatch")
        serialized = json.dumps(
            inputs, default=lambda v: v.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
        )
        result = OwnedLookResult(
            task_id=task_id,
            plan_id=plan_id,
            input_fingerprint=hashlib.sha256(serialized.encode()).hexdigest(),
            **output,
        )
        results[task_id] = result
        if trace is not None:
            trace.append(
                {
                    "task": task.model_dump(mode="json", by_alias=True),
                    "inputs": json.loads(serialized),
                    "result": result.model_dump(mode="json", by_alias=True),
                }
            )
        return result

    entries = [
        m
        for m in req._consultation_memories
        if m.structured and m.structured.key == "inventory.product"
    ]
    if len(entries) > CONSULTATION_MEMORY_LIMIT:
        raise ValueError("Server consultation memory limit exceeded")
    rows, failures = {}, []
    ids = list(
        dict.fromkeys(
            m.structured.value["productId"] for m in entries if m.structured.value.get("productId")
        )
    )
    queries = [{"ids": ids[i : i + 6]} for i in range(0, len(ids), 6)]
    queries.extend(
        {"q": m.structured.value["productName"]}
        for m in entries
        if not m.structured.value.get("productId")
    )
    for query in queries:
        try:
            found = await catalog.search_products(**query)
            if len({p.id for p in found}) != len(found):
                raise UpstreamError("Duplicate product identity")
            for product in found:
                validate_catalog_product(product)
                if query.get("ids") is None or product.id in query["ids"]:
                    rows[product.id] = product
        except (UpstreamError, ValueError):
            failures.append("보유 제품 일부를 현재 상품 정보와 대조하지 못했어요.")
    matches, unresolved = verified_inventory_matches(
        req, list(rows.values()), "exclude", match_names=True
    )
    owned = [
        OwnedLookProduct(
            memory_id=m.memory_id,
            memory_version=m.version,
            product_id=m.product_id,
            shade_id=m.shade_id,
            zone=rows[m.product_id].makeup_zone,
        )
        for m in matches
    ]
    o1 = record(
        "O1",
        "owned",
        {"queries": queries},
        status="partial" if unresolved or failures else "complete",
        owned_products=owned,
        limitations=failures,
    )

    style, _ = await execute_style(
        req.model_copy(update={"message": "이 룩의 전체 단계 순서를 알려줘."}), catalog
    )
    s1 = record(
        "S1",
        "style",
        {"look": req.style_context.model_dump(mode="json", by_alias=True), "scope": "all_steps"},
        status="complete" if style.style_recipe else "failed",
        recipe=style.style_recipe,
    )
    recipe = s1.recipe
    if recipe is None:
        style.products = []
        if style.style_status == "error" and req._owned_look_context is not None:
            style._owned_look_context = next_context(req, req._owned_look_context.recipe_version)
        return style
    verified_recipe = recipe.basis == "reviewed_recipe" and recipe.review_status == "verified"
    owned_state = next_context(req, recipe.recipe_version)
    declarations = owned_state.declarations
    absences = {zone: d.quote for zone, d in declarations.items() if d.status == "missing"}
    coverage = []
    for zone in dict.fromkeys(step.zone for step in recipe.steps):
        links = _exact_links(recipe, zone)
        owned_here = [
            m
            for m in o1.owned_products
            if any((m.product_id, m.shade_id) == (link.product_id, link.shade_id) for link in links)
        ]
        alternatives = [
            m.product_id for m in o1.owned_products if m.zone == zone and m not in owned_here
        ]
        if not verified_recipe or not links:
            state, reason = "evidence_missing", "검수된 룩의 정확한 상품·호수 근거가 부족해요."
        elif owned_here and zone not in absences:
            state, reason = "fulfilled", "보유 제품의 상품·호수가 검수 룩과 일치해요."
        elif zone in absences:
            state, reason = "confirmed_missing", "사용자가 해당 부위 제품이 없다고 밝혔어요."
        elif zone in declarations or alternatives:
            state, reason = (
                "evidence_missing",
                "보유한다고 알려주셨지만 정확한 상품·호수는 아직 확인하지 못했어요.",
            )
        else:
            state, reason = (
                "ownership_unknown",
                "등록 목록만으로 실제 보유 여부나 대체 적합성을 확정할 수 없어요.",
            )
        coverage.append(
            OwnedLookCoverage(
                zone=zone,
                status=state,
                product_ids=[m.product_id for m in owned_here],
                reason=reason,
                user_quote=declarations[zone].quote if zone in declarations else None,
                substitution_status="exact_match"
                if owned_here and verified_recipe
                else "unverified"
                if alternatives
                else "not_assessed",
                alternative_product_ids=alternatives,
                substitution_evidence=recipe.evidence_id
                if owned_here and verified_recipe
                else None,
            )
        )
    n1 = record(
        "N1",
        "needs",
        {"owned_products": o1.owned_products, "recipe": recipe, "explicitAbsences": absences},
        bindings=(("O1", "owned_products"), ("S1", "recipe")),
        status="complete" if all(c.status == "fulfilled" for c in coverage) else "partial",
        coverage=coverage,
    )

    candidate_rows, product_queries = {}, []
    filters = owned_state.filters
    unsupported_conditions = bool(filters.unsupported)
    if unsupported_conditions:
        failures.append(
            "요청하신 상품 조건 중 해석하거나 지원하지 못한 내용이 있어요. "
            "조건을 확인하기 전에는 추가 상품을 추천하지 않을게요."
        )
    for gap in n1.coverage:
        if gap.status != "confirmed_missing" or unsupported_conditions:
            continue
        target_ids = list(dict.fromkeys(link.product_id for link in _exact_links(recipe, gap.zone)))
        for i in range(0, len(target_ids), 6):
            query = {"ids": target_ids[i : i + 6]}
            product_queries.append({"zone": gap.zone, **query})
            try:
                for product in await catalog.search_products(**query):
                    validate_catalog_product(product)
                    if product.id in query["ids"]:
                        candidate_rows[product.id] = product
            except (UpstreamError, ValueError):
                failures.append("추가 후보 일부를 조회하지 못했어요.")
    refs = [
        ProductRef(id=p.id, brand=p.brand, name=p.name, category=p.category)
        for p in candidate_rows.values()
    ]
    p1 = record(
        "P1",
        "products",
        {"coverage": n1.coverage, "recipe": recipe, "queries": product_queries},
        bindings=(("N1", "coverage"), ("S1", "recipe")),
        status="partial" if failures else "complete" if product_queries else "skipped",
        products=refs,
    )
    option_results, option_requests, option_failures = [], [], []
    check_options = has_filters(filters)
    if check_options and not unsupported_conditions:
        ids = [p.id for p in p1.products]
        for i in range(0, len(ids), 6):
            option_request = OptionSearchRequest(
                product_ids=ids[i : i + 6],
                maxPriceKRW=filters.max_price_krw,
                price_basis=filters.price_basis,
                ingredient_conditions=filters.ingredient_conditions,
                fragrance_free=filters.fragrance_free,
            )
            option_requests.append(option_request.model_dump(mode="json", by_alias=True))
            try:
                if not hasattr(catalog, "search_options"):
                    raise UpstreamError("Option lookup unavailable")
                result = await catalog.search_options(option_request)
                if result.effective_request != option_request:
                    raise UpstreamError("Option request changed")
                option_results.append(result)
            except (UpstreamError, ValueError):
                option_failures.extend(option_request.product_ids)
    v1 = record(
        "V1",
        "options",
        {
            "products": p1.products,
            "recipe": recipe,
            "requests": option_requests,
            "userFilters": filters.model_dump(mode="json", by_alias=True),
        },
        bindings=(("P1", "products"), ("S1", "recipe")),
        status="partial"
        if option_failures or any(r.status != "SUCCESS" for r in option_results)
        else "complete"
        if option_requests
        else "skipped",
        option_searches=option_results,
        limitations=["옵션 조회 실패: " + pid for pid in option_failures],
    )
    eligible_options = {
        (item.product_id, item.shade_id)
        for result in v1.option_searches
        for item in result.items
        if item.group == "ELIGIBLE" and result.status != "ERROR"
    }
    selected, selected_ids = [], set()
    for gap in n1.coverage:
        if gap.status != "confirmed_missing":
            continue
        for link in _exact_links(recipe, gap.zone):
            product = candidate_rows.get(link.product_id)
            if (
                product
                and product.makeup_zone == gap.zone
                and any(s.id == link.shade_id for s in product.shades)
                and (not check_options or (product.id, link.shade_id) in eligible_options)
            ):
                selected_ids.add(product.id)
    selected = [p for p in p1.products if p.id in selected_ids]
    record(
        "R1",
        "review",
        {
            "products": p1.products,
            "recipe": recipe,
            "coverage": n1.coverage,
            "option_searches": v1.option_searches,
        },
        bindings=(
            ("P1", "products"),
            ("S1", "recipe"),
            ("N1", "coverage"),
            ("V1", "option_searches"),
        ),
        status="partial"
        if len(selected) != len(p1.products) or any(c.status != "fulfilled" for c in coverage)
        else "complete",
        products=selected,
    )

    names = dict(zip(ORDER, NAMES["ko"], strict=True))
    lines = [style.answer]
    for area in coverage:
        lines.append(f"{names[area.zone]}: {area.reason}")
    unknown = [names[c.zone] for c in coverage if c.status == "ownership_unknown"]
    if unknown:
        lines.append("추가로 필요한지 확인할게요. " + ", ".join(unknown) + " 제품도 가지고 있나요?")
    if selected:
        lines.append(
            "없다고 알려주신 부위에는 검수 룩에 연결된 상품의 같은 호수를 후보로 찾았어요."
        )
    if any(c.status == "confirmed_missing" for c in coverage) and not selected:
        lines.append("추가로 필요한 부위의 정확한 상품·호수를 다시 확인하지 못했어요.")
    if check_options:
        lines.append(
            "가격·성분 조건은 추가 추천 후보에 적용했어요. "
            "보유품의 성분 적합성은 별도로 확인해야 해요."
        )
        exact = {
            (link.product_id, link.shade_id)
            for gap in coverage
            if gap.status == "confirmed_missing"
            for link in _exact_links(recipe, gap.zone)
        }
        checked = [
            item
            for result in option_results
            for item in result.items
            if (item.product_id, item.shade_id) in exact
        ]
        counts = {
            group: sum(item.group == group for item in checked)
            for group in ("ELIGIBLE", "EXCLUDED", "REFERENCE_ONLY")
        }
        lines.append(
            f"조회된 해당 호수 옵션의 조건 확인 결과: 충족 {counts['ELIGIBLE']}개, "
            f"불일치 {counts['EXCLUDED']}개, 미확인 {counts['REFERENCE_ONLY']}개."
        )
        if option_failures:
            lines.append(
                "일부 상품의 옵션 조회에 실패했어요. 확인되지 않은 상품은 추천하지 않았어요."
            )
        if not checked and not option_failures:
            lines.append(
                "해당 호수의 옵션 근거를 확보하지 못했어요. 조건 충족으로 판단하지 않았어요."
            )
        if any(not r.checked_scope.exhaustive or r.omitted_count for r in option_results):
            lines.append("조회 범위가 제한되어 일부 옵션은 확인하지 못했어요.")
        if filters.max_price_krw is not None:
            lines.append("가격은 변동될 수 있어요. 구매 전에 상품 화면에서 다시 확인해 주세요.")
    if not entries:
        lines.append(
            "동의한 등록 목록에서 보유 제품을 확인하지 못했어요. 실제 미보유를 뜻하지는 않아요."
        )
    lines.extend(dict.fromkeys(failures))
    used = {pid for c in coverage if c.status == "fulfilled" for pid in c.product_ids}
    response = style.model_copy(
        update={
            "answer": "\n".join(lines),
            "products": selected,
            "applied_memories": [m for m in matches if m.product_id in used],
            "result_type": "recommendations"
            if selected
            else "clarification"
            if unknown
            else "empty",
        }
    )
    response._owned_look_context = owned_state
    return response
