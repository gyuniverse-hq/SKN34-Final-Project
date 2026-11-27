"""Read-only N02 first connection: exact recipe matches, not inferred substitutions."""

import hashlib
import json
import re
from uuid import uuid4

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.schemas.catalog import IngredientSelection, OptionSearchRequest
from app.schemas.chat import ChatResponse, ProductRef
from app.schemas.owned_look_consultation import (
    OwnedLookBinding,
    OwnedLookCoverage,
    OwnedLookProduct,
    OwnedLookResult,
    OwnedLookTask,
)
from app.schemas.owned_look_context import (
    OwnedLookContext,
    OwnedLookOptionDisplay,
    OwnedLookOptionRef,
    OwnedLookOutcome,
    OwnedLookOutcomeItem,
    OwnershipDeclaration,
)
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
                    req._owned_look_answer is not None
                    or declaration_updates(req.message)[0]
                    or declaration_updates(req.message)[1]
                    or (
                        _self_declaration(req.message)
                        and re.search(
                            r"(?:없어|있어|없고|있고)(?:요)?(?:[.,! ]|$)|조건\s*해제", req.message
                        )
                    )
                    or filter_followup(req.message)
                    or re.fullmatch(
                        r"(?:그럼\s*)?(?:다시\s*)?추천해\s*줘[.!]?", req.message.strip()
                    )
                )
            )
        )
    )


def _self_declaration(message):
    return not re.search(
        r"친구|엄마|동생|언니|누나|타인|다른\s*사람|기억|장바구니|\bAR\b|[?]|(?:라고|다는|다고)\s*(?:말|했|하)",
        message,
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
        if (link.zone == zone or (link.zone == "unknown" and link.consultation_zone == zone))
        and link.catalog_valid
        and link.mapping_status == "verified"
        and link.product_id
        and (link.shade_id or link.option_id)
    ]


def _reviewed_usage_matches(recipe, link, zone):
    """Usage evidence may fill a missing catalog zone, never override a conflicting one."""
    return bool(
        recipe.basis == "reviewed_recipe"
        and recipe.review_status == "verified"
        and recipe.evidence_id
        and link.product_usages
        and all(
            usage.product_id == link.product_id
            and usage.shade_id == link.shade_id
            and 1 <= usage.step_order <= len(recipe.steps)
            and recipe.steps[usage.step_order - 1].zone == zone
            and usage.evidence_id.strip()
            and usage.source.strip()
            for usage in link.product_usages
        )
    )


def _owns_link(memory, link):
    return memory.product_id == link.product_id and (
        memory.option_id is not None
        and link.option_id == memory.option_id
        or memory.option_id is None
        and memory.shade_id is not None
        and link.shade_id == memory.shade_id
    )


def _coverage_links(recipe, gap):
    return [
        link
        for link in _exact_links(recipe, gap.zone)
        if (link.product_id, link.option_id, link.shade_id)
        == (gap.product_id, gap.option_id, gap.shade_id)
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
    item_declarations = dict(previous.item_declarations) if same_recipe else {}
    updates, clear_all = declaration_updates(req.message)
    if clear_all:
        declarations.clear()
        item_declarations.clear()
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
        item_declarations=item_declarations,
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
    verified_options = {}
    for entry in entries:
        value = entry.structured.value
        pid, oid = value.get("productId"), value.get("optionId")
        if pid in rows and oid and (pid, oid) not in verified_options:
            try:
                option = await catalog.get_product_option(pid, oid)
                if option and (option.product_id, option.option_id) == (pid, oid):
                    verified_options[(pid, oid)] = option
            except UpstreamError:
                failures.append("보유 옵션 일부를 현재 상품 정보와 대조하지 못했어요.")
    matches, unresolved = verified_inventory_matches(
        req,
        list(rows.values()),
        "exclude",
        match_names=True,
        verified_options=verified_options,
    )
    owned = [
        OwnedLookProduct(
            memory_id=m.memory_id,
            memory_version=m.version,
            product_id=m.product_id,
            shade_id=m.shade_id,
            zone=rows[m.product_id].makeup_zone,
            option_id=next(
                (
                    entry.structured.value.get("optionId")
                    for entry in req._consultation_memories
                    if entry.id == m.memory_id
                ),
                None,
            ),
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
    released_zones = {
        zone for zone, value in declaration_updates(req.message)[0].items() if value is None
    }
    coverage = []
    for zone in dict.fromkeys(
        [step.zone for step in recipe.steps]
        + [p.consultation_zone for p in recipe.products if p.consultation_zone in ORDER]
    ):
        # Each exact option is a separate coverage target, even within one zone.
        # Repeated listings of the same option are consolidated; usage steps stay attached.
        unique = {}
        for link in recipe.products:
            if link.zone == zone or (link.zone == "unknown" and link.consultation_zone == zone):
                identity = (
                    link.product_id,
                    link.option_id,
                    link.shade_id,
                    link.label if not (link.option_id or link.shade_id) else None,
                )
                unique.setdefault(identity, link)
        for identity, link in list(unique.items()) or [(None, None)]:
            need_id = hashlib.sha256(
                json.dumps([recipe.recipe_version, zone, identity], ensure_ascii=False).encode()
            ).hexdigest()
            label = link.label if link else dict(zip(ORDER, NAMES["ko"], strict=True))[zone]
            if link and sum(p.label == link.label for p in recipe.products) > 1:
                option_label = link.option_name or link.option_id or link.shade_id or "옵션 미확인"
                label += f" ({option_label})"
            if zone in released_zones:
                owned_state.item_declarations.pop(need_id, None)
            declaration = owned_state.item_declarations.get(need_id)
            targeted = req._owned_look_answer
            if targeted and targeted[:2] == (need_id, recipe.recipe_version):
                declaration = OwnershipDeclaration(
                    status="missing" if targeted[2] == "없어" else "present",
                    quote=targeted[2],
                    confirmed_current=True,
                )
                owned_state.item_declarations[need_id] = declaration
            # Only unique exact labels/IDs can establish a product-level declaration.
            # Generic zone declarations retain their explicitly broader scope.
            if link and _self_declaration(req.message):
                aliases = [label, link.label, link.option_name, link.option_id, link.product_id]
                for alias in filter(None, aliases):
                    if alias != label and (
                        sum(
                            alias in (p.label, p.option_name, p.option_id, p.product_id)
                            for p in recipe.products
                        )
                        != 1
                    ):
                        continue
                    match = re.search(
                        re.escape(alias)
                        + r"(?:은|는|이|가)?\s*(없어|있어|없고|있고)(?:요)?(?:[.,! ]|$)",
                        req.message,
                    )
                    release = re.search(
                        re.escape(alias) + r"(?:의)?\s*(?:미보유|보유)?\s*조건\s*해제", req.message
                    )
                    if release:
                        owned_state.item_declarations.pop(need_id, None)
                        declaration = None
                        break
                    if match:
                        declaration = OwnershipDeclaration(
                            status="missing" if match[1].startswith("없") else "present",
                            quote=match[0].strip(),
                        )
                        owned_state.item_declarations[need_id] = declaration
                        break
            declaration = declaration or declarations.get(zone)
            owned_here = [m for m in o1.owned_products if link and _owns_link(m, link)]
            # Other listed products are not inferred substitutes for this target.
            alternatives = [
                m.product_id
                for m in o1.owned_products
                if m.zone == zone
                and m not in owned_here
                and not any(_owns_link(m, p) for p in _exact_links(recipe, zone))
            ]
            if link is None or link not in _exact_links(recipe, zone):
                state, reason = (
                    "evidence_missing",
                    "이 부위에 연결된 정확한 상품·옵션은 아직 확인하지 못했어요.",
                )
            elif (
                owned_here
                and declaration
                and declaration.status == "missing"
                and need_id in owned_state.item_declarations
                and not declaration.confirmed_current
            ):
                state, reason = (
                    "ownership_unknown",
                    "저장한 보유 정보와 이번 답변이 달라요. 현재 보유 여부를 다시 확인해 주세요.",
                )
            elif (owned_here and not (declaration and declaration.status == "missing")) or (
                declaration
                and declaration.status == "present"
                and need_id in owned_state.item_declarations
            ):
                state, reason = (
                    "fulfilled",
                    "영상·룩에 연결된 상품·옵션과 같은 제품의 보유를 확인했어요.",
                )
            elif declaration and declaration.status == "missing":
                state, reason = (
                    "confirmed_missing",
                    "사용자가 해당 상품 또는 부위 제품이 없다고 밝혔어요.",
                )
            elif declaration or alternatives:
                state, reason = (
                    "evidence_missing",
                    (
                        "보유 제품은 확인했지만 이 룩의 대체품으로 적합한지는 "
                        "아직 확인하지 못했어요."
                        if alternatives
                        else "보유한다고 알려주셨지만 정확한 상품·호수는 아직 확인하지 못했어요."
                    ),
                )
            else:
                state, reason = (
                    "ownership_unknown",
                    "등록 목록만으로 실제 보유 여부나 대체 적합성을 확정할 수 없어요.",
                )
            reviewed = link and _reviewed_usage_matches(recipe, link, zone)
            coverage.append(
                OwnedLookCoverage(
                    need_id=need_id,
                    zone=zone,
                    label=label,
                    product_id=link.product_id if link else None,
                    option_id=link.option_id if link else None,
                    shade_id=link.shade_id if link else None,
                    step_orders=sorted(
                        {
                            u.step_order
                            for p in _exact_links(recipe, zone)
                            if link
                            and (p.product_id, p.option_id, p.shade_id) == identity[:3]
                            and _reviewed_usage_matches(recipe, p, zone)
                            for u in p.product_usages
                        }
                    ),
                    role_basis="reviewed_usage" if reviewed else "product_listing",
                    status=state,
                    product_ids=[m.product_id for m in owned_here],
                    reason=reason,
                    user_quote=declaration.quote if declaration else None,
                    substitution_status="exact_match"
                    if owned_here
                    else "unverified"
                    if alternatives
                    else "not_assessed",
                    alternative_product_ids=alternatives,
                    substitution_evidence=recipe.evidence_id if owned_here else None,
                )
            )
    valid_ids = {c.need_id for c in coverage}
    owned_state.item_declarations = {
        k: v for k, v in owned_state.item_declarations.items() if k in valid_ids
    }
    n1 = record(
        "N1",
        "needs",
        {"owned_products": o1.owned_products, "recipe": recipe, "explicitAbsences": absences},
        bindings=(("O1", "owned_products"), ("S1", "recipe")),
        status="complete" if all(c.status == "fulfilled" for c in coverage) else "partial",
        coverage=coverage,
    )

    candidate_rows, product_queries = {}, []
    attempted_ids, failed_candidate_ids = set(), set()
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
        target_ids = list(
            dict.fromkeys(
                link.product_id
                for link in _coverage_links(recipe, gap)
                if link.product_id not in attempted_ids
            )
        )
        attempted_ids.update(target_ids)
        for i in range(0, len(target_ids), 6):
            query = {"ids": target_ids[i : i + 6]}
            product_queries.append({"zone": gap.zone, **query})
            try:
                for product in await catalog.search_products(**query):
                    validate_catalog_product(product)
                    if product.id in query["ids"]:
                        candidate_rows[product.id] = product
            except (UpstreamError, ValueError):
                failed_candidate_ids.update(query["ids"])
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
    check_options = has_filters(filters) or any(link.option_id for link in recipe.products)
    if check_options and not unsupported_conditions:
        ids = [p.id for p in p1.products]
        scoped_ids = {link.product_id for link in recipe.products if link.option_id}
        groups = [
            [pid for pid in ids if pid in scoped_ids],
            [pid for pid in ids if pid not in scoped_ids],
        ]
        for batch_ids in [group[i : i + 6] for group in groups for i in range(0, len(group), 6)]:
            scope = [
                IngredientSelection(
                    product_id=link.product_id, shade_id=link.shade_id, option_id=link.option_id
                )
                for gap in coverage
                if gap.status == "confirmed_missing"
                for link in _coverage_links(recipe, gap)
                if link.product_id in batch_ids and link.option_id
            ]
            option_request = OptionSearchRequest(
                product_ids=batch_ids,
                option_scope=scope or None,
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
    # Catalog currently has no live-price evidence type. Without a budget it may
    # omit the price check altogether; ELIGIBLE alone does not verify this user request.
    current_price_unverified = filters.price_basis == "current_offer"
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
        if current_price_unverified
        or option_failures
        or any(r.status != "SUCCESS" for r in option_results)
        else "complete"
        if option_requests
        else "skipped",
        option_searches=option_results,
        limitations=["옵션 조회 실패: " + pid for pid in option_failures]
        + (["실시간 현재가 근거 미확인"] if current_price_unverified else []),
    )
    option_failures.extend(
        pid
        for result in option_results
        if result.status == "ERROR"
        for pid in result.effective_request.product_ids
    )
    eligible_options = {
        (item.product_id, item.shade_id, item.option_id)
        for result in v1.option_searches
        for item in result.items
        if item.group == "ELIGIBLE" and result.status != "ERROR" and not current_price_unverified
    }
    selected, selected_ids = [], set()
    resolved_needs = set()
    option_refs = {}
    for gap in n1.coverage:
        if gap.status != "confirmed_missing":
            continue
        for link in _coverage_links(recipe, gap):
            product = candidate_rows.get(link.product_id)
            if (
                product
                and (
                    product.makeup_zone == gap.zone
                    or (
                        product.makeup_zone is None
                        and (
                            link.consultation_zone == gap.zone
                            or _reviewed_usage_matches(recipe, link, gap.zone)
                        )
                    )
                )
                and (link.option_id or any(s.id == link.shade_id for s in product.shades))
                and (
                    not check_options
                    or any(
                        pid == product.id
                        and sid == link.shade_id
                        and (not link.option_id or oid == link.option_id)
                        for pid, sid, oid in eligible_options
                    )
                )
            ):
                selected_ids.add(product.id)
                resolved_needs.add(gap.need_id)
                if check_options:
                    for batch in option_results:
                        if batch.status == "ERROR":
                            continue
                        for item in batch.items:
                            if (
                                (item.product_id, item.shade_id)
                                != (
                                    product.id,
                                    link.shade_id,
                                )
                                or (link.option_id and item.option_id != link.option_id)
                                or item.group != "ELIGIBLE"
                            ):
                                continue
                            option_refs[(item.product_id, item.shade_id, item.option_id)] = (
                                OwnedLookOptionRef(
                                    product_id=product.id,
                                    shade_id=link.shade_id,
                                    option_id=item.option_id,
                                    product_name=product.name,
                                    brand=product.brand,
                                    shade_name=item.option_name
                                    or next(
                                        (s.name for s in product.shades if s.id == link.shade_id),
                                        link.option_name or item.option_id,
                                    ),
                                )
                            )
    selected = [p for p in p1.products if p.id in selected_ids]
    outcome_items = []
    for gap in coverage:
        if gap.status == "fulfilled":
            status = "owned"
        elif gap.need_id in resolved_needs:
            status = "recommended"
        elif gap.status in {"ownership_unknown", "evidence_missing"}:
            status = gap.status
        elif gap.product_id in failed_candidate_ids or gap.product_id in option_failures:
            status = "lookup_failed"
        else:
            checked_items = [
                item
                for batch in option_results
                if batch.status != "ERROR"
                for item in batch.items
                if item.product_id == gap.product_id
                and item.shade_id == gap.shade_id
                and (not gap.option_id or item.option_id == gap.option_id)
            ]
            status = (
                "excluded"
                if checked_items and all(item.group == "EXCLUDED" for item in checked_items)
                else "evidence_missing"
            )
        outcome_items.append(
            OwnedLookOutcomeItem(need_id=gap.need_id, zone=gap.zone, label=gap.label, status=status)
        )
    states = [i.status for i in outcome_items]
    outcome = OwnedLookOutcome(
        status="waiting_user"
        if "ownership_unknown" in states
        else "completed"
        if states and all(s in {"owned", "recommended"} for s in states)
        else "failed"
        if states and all(s == "lookup_failed" for s in states)
        else "partial",
        items=outcome_items,
    )
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
        status="complete" if outcome.status == "completed" else outcome.status,
        products=selected,
        coverage=coverage,
        outcome=outcome,
    )

    names = dict(zip(ORDER, NAMES["ko"], strict=True))
    lines = [style.answer]
    if not verified_recipe:
        lines.append(
            "상품 연결 정보로 보유품과 추가 후보를 확인했어요. "
            "안내한 순서는 일반 가이드이며 영상의 실제 사용 순서를 확인한 것은 아니에요."
        )
    product_only = [
        p for p in recipe.products if p.product_id and p.mapping_status == "product_only"
    ]
    if product_only:
        lines.append(
            "상품 연결은 확인했지만 정확한 판매 옵션은 미확인이에요: "
            + ", ".join(p.label for p in product_only)
        )
    for area in coverage:
        lines.append(f"{names[area.zone]} · {area.label}: {area.reason}")
        for pid in area.alternative_product_ids:
            product = rows[pid]
            details = [v for v in [product.texture, ", ".join(s.name for s in product.shades)] if v]
            lines.append(
                f"보유한 {product.brand} {product.name}도 같은 부위의 활용 후보예요. "
                + ("등록 정보: " + " / ".join(details) + ". " if details else "")
                + "영상 제품과 같은 색·표현인지는 확인되지 않았어요. "
                "먼저 보유품을 활용할지 선택할 수 있어요."
            )
    if any(
        sum(c.zone == area.zone for c in coverage) > 1 and area.role_basis == "product_listing"
        for area in coverage
    ):
        lines.append(
            "같은 부위의 여러 상품은 각각 확인했어요. "
            "목록만으로 모두 함께 써야 하는지, 서로 대체할 수 있는지는 알 수 없어요."
        )
    unknown = [c.label for c in coverage if c.status == "ownership_unknown"]
    if unknown:
        lines.append("추가로 필요한지 확인할게요. " + ", ".join(unknown) + " 제품도 가지고 있나요?")
    if selected:
        lines.append("없다고 알려주신 부위에는 영상·룩 목록에 연결된 상품·옵션을 후보로 찾았어요.")
    if any(c.status == "confirmed_missing" for c in coverage) and not selected:
        lines.append(
            "추가 후보를 확정하지 못했어요. 조건 불일치·근거 부족·조회 실패를 구분해 확인해야 해요."
        )
    for item in outcome.items:
        if item.status == "excluded":
            lines.append(f"{item.label}: 요청한 조건에 맞지 않아 추가 후보에서 제외했어요.")
        elif item.status == "lookup_failed":
            lines.append(f"{item.label}: 조회에 실패했어요. 확인된 다른 결과는 유지했어요.")
        elif item.status == "evidence_missing":
            lines.append(f"{item.label}: 현재 자료로 적합한 추가 후보를 확정하지 못했어요.")
    if has_filters(filters):
        lines.append(
            "가격·성분 조건은 추가 추천 후보에 적용했어요. "
            "보유품의 성분 적합성은 별도로 확인해야 해요."
        )
    if check_options:
        exact = {
            (link.product_id, link.shade_id, link.option_id)
            for gap in coverage
            if gap.status == "confirmed_missing"
            for link in _coverage_links(recipe, gap)
        }
        checked = [
            item
            for result in option_results
            for item in result.items
            if any(
                item.product_id == pid
                and item.shade_id == sid
                and (oid is None or item.option_id == oid)
                for pid, sid, oid in exact
            )
        ]
        counts = {
            group: sum(
                (
                    "REFERENCE_ONLY"
                    if current_price_unverified and item.group == "ELIGIBLE"
                    else item.group
                )
                == group
                for item in checked
            )
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
    used = {
        m.memory_id
        for c in coverage
        if c.status == "fulfilled"
        for link in _coverage_links(recipe, c)
        for m in owned
        if _owns_link(m, link)
    }
    response = style.model_copy(
        update={
            "answer": "\n".join(lines),
            "products": selected,
            "applied_memories": [m for m in matches if m.memory_id in used],
            "result_type": "recommendations"
            if selected
            else "clarification"
            if unknown
            else "empty",
        }
    )
    if check_options:
        response.owned_look_options = OwnedLookOptionDisplay(
            selections=list(option_refs.values()),
            batches=option_results,
            failed_product_ids=option_failures,
        )
        if filters.price_basis == "current_offer":
            response.answer += (
                "\n실시간 현재가는 확인하지 못했어요. "
                "가격 정보의 확인 시점과 구매 화면을 확인해 주세요."
            )
    response._owned_look_context = owned_state
    response._owned_look_outcome = outcome
    return response
