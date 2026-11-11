"""Connect published ingredient claims to reviewed, exact catalog options."""

import asyncio
import re
import time
import unicodedata
from dataclasses import dataclass, field

from app.clients.catalog_client import UnsupportedOptionCategory
from app.core.errors import ApiError, UpstreamError
from app.schemas.catalog import (
    BudgetDecision,
    CatalogOption,
    ClaimContext,
    ClaimIngredientKey,
    ClaimLookup,
    IngredientDecision,
    OptionFilter,
    OptionLookup,
)
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    OptionClaimLink,
    OptionCondition,
    OptionConversation,
    OptionEvaluation,
    OptionSearchResult,
    ProductRef,
)
from app.schemas.supervisor import SearchPlan, ToolResult
from app.services.beauty_consultation_service import _context, _effective_filters, _plan_conditions

PAGE_LIMIT = 4
PAGE_SIZE = 32
OPTION_DEADLINE = 20
CLAIM_DEADLINE = 8
MAX_CARDS = 6

CREAM = {"크림", "cream", "クリーム", "面霜", "乳霜"}
CAPTURED_PRICE = re.compile(
    r"수집가|수집\s*(?:당시|시점)|과거\s*(?:판매)?가(?:격)?|"
    r"(?:captured|historical|collected)\s+(?:sale\s+)?price|収集時|采集时|历史售价",
    re.I,
)
CURRENT_PRICE = re.compile(r"현재\s*(?:판매가|가격|가)|오늘|지금|current|today|現在|当前", re.I)
AVOID_REQUEST = re.compile(r"피해(?:야|도)|피할|회피|\bavoid\b|避け|避开|避免", re.I)

TEXT = {
    "ko": {
        "missing": "이 요청에 적용할 수 있는 발행 근거를 확인하지 못했습니다.",
        "error": "근거 조회에 실패했습니다.",
        "no_matches": "조회한 범위에서 조건을 충족한 옵션이 없습니다.",
        "incomplete": "검색이 완료되지 않았습니다. 확인한 범위의 결과입니다.",
        "unconfirmed": "필수 조건에 미확인 항목이 있습니다.",
        "partial_failure": "옵션 정보 일부를 조회하지 못했습니다. 확인한 범위의 결과입니다.",
        "unsupported_category": "카탈로그에서 확인할 수 있는 세부 카테고리를 알려주세요.",
        "select": "확인할 후보 상품의 순번을 알려주세요.",
        "matches": "조회한 범위에서 조건이 확인된 옵션입니다.",
        "detail": "선택한 옵션에서 확인한 정보입니다.",
        "current": "현재 판매가",
        "collected": "수집 당시 판매가",
        "unknown": "미확인",
        "contains": "검수된 표시 성분에서 함유 확인",
        "absent": "검수한 전체 전성분에서 해당 성분명 부재 확인",
        "condition_error": "조회 실패",
        "research": "성분 연구 근거",
        "limitation": (
            "성분 연구 및 함유 정보로 확인된 범위입니다. 완제품 효능과 개인 적합성은 미확인입니다."
        ),
    },
    "en": {
        "missing": "No published evidence was confirmed for this request.",
        "error": "The evidence lookup failed.",
        "no_matches": "No option matched in the checked scope.",
        "incomplete": "The search is incomplete. Results cover the checked scope.",
        "unconfirmed": "Some required conditions are unconfirmed.",
        "partial_failure": (
            "Some option data could not be retrieved. Results cover the checked scope."
        ),
        "unsupported_category": "Specify a catalog subcategory.",
        "select": "Specify the number of the candidate product.",
        "matches": "These options met the conditions in the checked scope.",
        "detail": "Verified information for the selected option:",
        "current": "Current sale price",
        "collected": "Captured sale price",
        "unknown": "unconfirmed",
        "contains": "Present in the reviewed ingredients",
        "absent": "Absent from the reviewed full ingredient list",
        "condition_error": "lookup failed",
        "research": "Ingredient research",
        "limitation": "Finished-product efficacy and individual suitability remain unconfirmed.",
    },
    "ja": {
        "missing": "この条件に該当する公開済みの根拠は確認できませんでした。",
        "error": "根拠の取得に失敗しました。",
        "no_matches": "確認した範囲に条件を満たすオプションはありません。",
        "incomplete": "検索は完了していません。確認した範囲の結果です。",
        "unconfirmed": "必須条件に未確認の項目があります。",
        "partial_failure": "一部のオプション情報を取得できませんでした。確認した範囲の結果です。",
        "unsupported_category": "カタログの詳細カテゴリを指定してください。",
        "select": "確認する候補商品の番号を指定してください。",
        "matches": "確認した範囲で条件を満たすオプションです。",
        "detail": "選択したオプションで確認した情報です。",
        "current": "現在の販売価格",
        "collected": "収集時の販売価格",
        "unknown": "未確認",
        "contains": "確認済みの成分表に記載あり",
        "absent": "確認済みの全成分表に該当成分の記載なし",
        "condition_error": "取得失敗",
        "research": "成分の研究根拠",
        "limitation": "製品としての効能や個人への適合性は未確認です。",
    },
    "zh": {
        "missing": "未查到适用于本次请求的已发布证据。",
        "error": "证据查询失败。",
        "no_matches": "在已核查的范围内没有符合条件的选项。",
        "incomplete": "搜索尚未完成。结果仅涵盖已核查范围。",
        "unconfirmed": "部分必选条件尚未确认。",
        "partial_failure": "部分选项信息未能获取。结果仅涵盖已核查范围。",
        "unsupported_category": "请指定目录中的细分类别。",
        "select": "请指定要查看的候选商品序号。",
        "matches": "以下选项在已核查的范围内符合条件。",
        "detail": "以下是所选选项中已核查的信息。",
        "current": "当前售价",
        "collected": "采集时售价",
        "unknown": "未确认",
        "contains": "在经审核的成分表中确认含有",
        "absent": "经审核的完整成分表中未列出该成分",
        "condition_error": "查询失败",
        "research": "成分研究证据",
        "limitation": "成品功效与个人适用性尚未确认。",
    },
}


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _mentions(message: str, term: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(_normalized(term))}", _normalized(message)))


def option_requested(
    req: ChatRequest, plan: SearchPlan, previous: OptionConversation | None
) -> bool:
    if (
        plan.intent == "general"
        or plan.compare_ordinals
        or getattr(req.screen_context, "ingredient_comparison", None)
    ):
        return False
    if plan.evidence_intent == "recommend" or plan.option_category:
        return True
    return bool(
        previous
        and (
            plan.intent == "refine"
            or (plan.intent in {"detail", "price"} and not plan.query and not plan.shade_name)
        )
    )


def _scope(req, plan, previous=None, *, for_option=False):
    original = previous.claim_context if previous else ClaimContext()
    supplied = plan.claim_context or ClaimContext()
    values = original.model_dump()
    for field_name in ("concern", "target", "formulation"):
        value = getattr(supplied, field_name)
        if value and _mentions(req.message, value):
            values[field_name] = value
    # A requested formulation/concentration does not establish what an option contains.
    values["concentration_pct"] = None
    if for_option:
        values["formulation"] = None
    elif len(plan.explanation_ingredients) == 1 and supplied.concentration_pct is not None:
        name = _normalized(plan.explanation_ingredients[0])
        number = re.search(
            rf"(?<!\w){re.escape(name)}\s*(?:농도\s*)?(\d+(?:\.\d+)?)\s*%", _normalized(req.message)
        )
        if number and float(number[1]) == supplied.concentration_pct:
            values["concentration_pct"] = supplied.concentration_pct
    return ClaimContext(**values)


def _citation_text(claim):
    return f"{claim.ingredient_name} · {claim.summary}\n{claim.source_title} ({claim.source_url})"


async def _claims(catalog, lookup):
    try:
        async with asyncio.timeout(CLAIM_DEADLINE):
            result = await catalog.search_claims(lookup)
    except (UpstreamError, TimeoutError):
        return "unavailable", []
    claims = [claim for claim in result.claims if claim.use == lookup.use]
    return ("available" if claims else "not_found"), claims


async def explain_ingredients(req, plan, catalog):
    words = TEXT[req.locale]
    scope = _scope(req, plan)
    names = list(
        dict.fromkeys(
            name
            for name in plan.explanation_ingredients
            if 0 < len(name.strip()) <= 80 and _mentions(req.message, name)
        )
    )
    status, claims = "not_found", []
    if names and catalog is not None:
        use = (
            "avoid"
            if plan.explanation_use == "avoid" and AVOID_REQUEST.search(req.message)
            else "explain"
        )
        status, claims = await _claims(
            catalog, ClaimLookup(use=use, context=scope, ingredient_names=names)
        )
    answer = "\n\n".join(_citation_text(claim) for claim in claims)
    response = ChatResponse(
        answer=answer or words["error" if status == "unavailable" else "missing"],
        products=[],
        published_claims=claims,
        claim_status=status,
        claim_context=scope,
    )
    return response, ToolResult(
        tool="knowledge",
        status="error" if status == "unavailable" else "success",
        reason=None if claims else f"claim_{status}",
    )


async def revalidate_claims(response, scope, catalog):
    old = response.published_claims
    if not old:
        return
    if scope is None or catalog is None:
        raise ApiError(503, "Published evidence unavailable", "claim_lookup_failed")
    status, current = await _claims(
        catalog,
        ClaimLookup(use=old[0].use, context=scope, publication_ids=[c.publication_id for c in old]),
    )
    if status == "unavailable":
        raise ApiError(503, "Published evidence unavailable", "claim_lookup_failed")
    if {c.publication_id: c for c in current} != {c.publication_id: c for c in old}:
        raise ApiError(409, "Published evidence changed; ask again", "chat_evidence_changed")


async def revalidate_option_evidence(response, catalog):
    """Redis is conversation history, never an authoritative ingredient snapshot."""
    legacy = []
    for result in response.ingredient_results or []:
        checks = [c for c in result.conditions if c.verdict in {"MATCH", "NOT_MATCH"}]
        if checks or result.verified:
            legacy.append((result, checks or [None]))
    if legacy:
        if catalog is None:
            raise ApiError(503, "Option evidence unavailable", "option_evidence_lookup_failed")
        if sum(len(checks) for _, checks in legacy) > MAX_CARDS:
            raise ApiError(409, "Option search must be refreshed", "chat_option_evidence_changed")
        try:
            async with asyncio.timeout(OPTION_DEADLINE):
                for old, checks in legacy:
                    for condition in checks:
                        current = await catalog.get_ingredients(
                            old.product_id,
                            old.shade_id,
                            ingredient_name=condition.ingredient_name if condition else None,
                            operator=condition.operator if condition else "includes",
                        )
                        if current.status == "error" or current.verdict == "ERROR":
                            raise ApiError(
                                503, "Option evidence unavailable", "option_evidence_lookup_failed"
                            )
                        fields = (
                            "option_id",
                            "source_version",
                            "evidence_id",
                            "ingredients",
                            "review_status",
                            "ingredient_coverage",
                            "normalization_status",
                        )
                        if any(getattr(current, key) != getattr(old, key) for key in fields) or (
                            condition is not None and current.conditions != [condition]
                        ):
                            raise ApiError(
                                409, "Option evidence changed", "chat_option_evidence_changed"
                            )
        except (UpstreamError, TimeoutError) as exc:
            raise ApiError(
                503, "Option evidence unavailable", "option_evidence_lookup_failed"
            ) from exc
    search = response.option_search
    if search is None or not search.evaluations:
        return
    if catalog is None or not search.category_id:
        raise ApiError(503, "Option evidence unavailable", "option_evidence_lookup_failed")
    # Bound retry work; large stored searches must be run again, not served stale.
    if len(search.evaluations) > MAX_CARDS:
        raise ApiError(409, "Option search must be refreshed", "chat_option_evidence_changed")
    try:
        async with asyncio.timeout(OPTION_DEADLINE):
            for old in search.evaluations:
                request = OptionLookup(
                    category_id=search.category_id,
                    product_id=old.product_id,
                    option_id=old.option_id,
                    price_basis=search.price_basis,
                    limit=1,
                    max_price_krw=old.budget.max_price_krw if old.budget else None,
                    ingredient_conditions=[
                        OptionFilter(ingredient_name=c.ingredient_name, operator=c.operator)
                        for c in old.ingredient_conditions
                    ],
                )
                page = await catalog.search_options(request)
                rows = [*page.matches, *page.excluded, *page.unconfirmed]
                if page.scope.options_with_lookup_errors:
                    raise ApiError(
                        503, "Option evidence unavailable", "option_evidence_lookup_failed"
                    )
                if (
                    len(rows) != 1
                    or rows[0].option_id != old.option_id
                    or rows[0].product_id != old.product_id
                ):
                    raise ApiError(409, "Option evidence changed", "chat_option_evidence_changed")
                row = rows[0]
                review = row.ingredients.review
                if row.ingredients.error_code:
                    raise ApiError(
                        503, "Option evidence unavailable", "option_evidence_lookup_failed"
                    )
                if (
                    review.source_version != old.ingredient_source_version
                    or review.evidence_id != old.ingredient_evidence_id
                    or ("verified" if review.verified else "unknown") != old.ingredient_verification
                    or review.ingredient_coverage != old.ingredient_coverage
                    or review.conditions != old.ingredient_conditions
                    or row.price != old.price
                    or row.budget_condition != old.budget
                ):
                    raise ApiError(409, "Option evidence changed", "chat_option_evidence_changed")
    except (UpstreamError, TimeoutError) as exc:
        raise ApiError(503, "Option evidence unavailable", "option_evidence_lookup_failed") from exc


async def _category(catalog, label):
    requested = _normalized(label)
    terms = CREAM if requested in CREAM else {requested}
    values = await catalog.option_categories()
    matches = {
        c.category_id
        for c in values.categories
        if terms.intersection(_normalized(name) for name in (c.name, c.path) if name)
    }
    parents = {c.category_id: c.parent_id for c in values.categories}
    ancestors = set()
    for category_id in matches:
        seen = {category_id}
        parent = parents.get(category_id)
        while parent and parent not in seen:
            ancestors.add(parent)
            seen.add(parent)
            parent = parents.get(parent)
    leaves = matches - ancestors
    return next(iter(leaves)) if len(leaves) == 1 else None


@dataclass
class _Scan:
    rows: list[CatalogOption] = field(default_factory=list)
    total: int | None = None
    pages: int = 0
    exhaustive: bool = False
    failed: bool = False
    stop: str = "page_limit"


async def _scan(catalog, lookup, selections):
    scan = _Scan()
    seen = set()
    requests = (
        [
            lookup.model_copy(update={"product_id": pid, "option_id": oid, "limit": 1})
            for pid, oid in selections.items()
        ]
        if selections is not None
        else [lookup] * PAGE_LIMIT
    )
    if not requests:
        return _Scan(total=0, exhaustive=True, stop="complete")
    offset = 0
    try:
        async with asyncio.timeout(OPTION_DEADLINE):
            for request in requests:
                if selections is None:
                    request = request.model_copy(update={"offset": offset})
                page = await catalog.search_options(request)
                scope = page.scope
                rows = [*page.matches, *page.excluded, *page.unconfirmed]
                keys = {row.option_id for row in rows}
                count = scope.candidate_count
                stop = request.offset + len(rows)
                if (
                    scope.request != request
                    or scope.category.category_id != lookup.category_id
                    or scope.evaluated_count != len(rows)
                    or len(rows) > request.limit
                    or len(keys) != len(rows)
                    or keys & seen
                    or len(rows) != min(request.limit, max(0, count - request.offset))
                    or scope.next_offset != (stop if stop < count else None)
                    or (selections is None and scan.total not in (None, count))
                    or any(
                        row.category.category_id != lookup.category_id
                        or (request.product_id and row.product_id != request.product_id)
                        or (request.option_id and row.option_id != request.option_id)
                        for row in rows
                    )
                ):
                    scan.failed, scan.stop = True, "catalog_scope_changed"
                    return scan
                seen.update(keys)
                scan.pages += 1
                scan.rows.extend(rows)
                scan.failed |= bool(scope.options_with_lookup_errors)
                if selections is not None:
                    scan.total = (scan.total or 0) + count
                else:
                    scan.total = count
                    if scope.next_offset is None:
                        scan.exhaustive, scan.stop = True, "complete"
                        break
                    offset = scope.next_offset
            else:
                if selections is not None:
                    scan.exhaustive, scan.stop = True, "complete"
    except UnsupportedOptionCategory:
        scan.stop = "unsupported_category" if not scan.pages else "catalog_scope_changed"
        scan.failed = bool(scan.pages)
    except TimeoutError:
        scan.failed, scan.stop = True, "time_limit"
    except UpstreamError:
        scan.failed, scan.stop = True, "lookup_failed"
    return scan


def _verdict(values):
    return next((v for v in ("NOT_MATCH", "ERROR", "UNKNOWN") if v in values), "MATCH")


def _reviewed(row):
    review = row.ingredients.review
    return (
        not row.ingredients.error_code
        and review.verified
        and (review.product_id, review.option_id) == (row.product_id, row.option_id)
    )


def _evaluation(row, lookup, filters, require_in_stock):
    review = row.ingredients.review
    checked = {
        (_normalized(c.ingredient_name), c.operator): c
        for c in review.conditions
        if (c.product_id, c.option_id) == (row.product_id, row.option_id)
    }
    ingredients = []
    for condition in lookup.ingredient_conditions:
        decision = checked.get((_normalized(condition.ingredient_name), condition.operator))
        if decision is None or (decision.verdict in {"MATCH", "NOT_MATCH"} and not _reviewed(row)):
            decision = IngredientDecision(
                product_id=row.product_id,
                option_id=row.option_id,
                shade_id=None,
                condition="ingredient",
                ingredient_name=condition.ingredient_name,
                operator=condition.operator,
                verdict="ERROR",
                reason="invalid_option_condition",
            )
        ingredients.append(decision)
    budget = row.budget_condition
    if lookup.max_price_krw is None:
        budget = None
    elif (
        budget is None
        or budget.price_basis != lookup.price_basis
        or budget.max_price_krw != lookup.max_price_krw
    ):
        budget = BudgetDecision(
            price_basis=lookup.price_basis,
            max_price_krw=lookup.max_price_krw,
            verdict="ERROR",
            reason="invalid_option_budget",
        )
    elif budget.verdict == "MATCH" and (
        (lookup.price_basis == "current_sale" and row.price.current_sale_price_krw is None)
        or (
            lookup.price_basis == "collected_sale"
            and (not row.price.collected or row.price.collected.sale_price_krw is None)
        )
    ):
        budget = budget.model_copy(update={"verdict": "ERROR", "reason": "missing_option_price"})
    other = []
    if require_in_stock:
        stock = row.price.current_stock_status
        verdict = {"in_stock": "MATCH", "sold_out": "NOT_MATCH", "unknown": "UNKNOWN"}[stock]
        other.append(OptionCondition(condition="stock", verdict=verdict, reason=f"current_{stock}"))
    if filters.fragrance_free:
        other.append(
            OptionCondition(
                condition="fragrance_free", verdict="UNKNOWN", reason="fragrance_group_unverified"
            )
        )
    if filters.query and _normalized(filters.query) not in _normalized(row.product_name):
        other.append(
            OptionCondition(
                condition="product_query",
                verdict="NOT_MATCH",
                reason="option_product_name_mismatch",
            )
        )
    verdicts = [row.required_verdict, *(item.verdict for item in [*ingredients, *other])]
    if budget:
        verdicts.append(budget.verdict)
    verified = _reviewed(row)
    return OptionEvaluation(
        product_id=row.product_id,
        option_id=row.option_id,
        option_name=row.option_name,
        verdict=_verdict(verdicts),
        price=row.price,
        budget=budget,
        ingredient_conditions=ingredients,
        other_conditions=other,
        ingredient_verification=(
            "verified" if verified else "error" if row.ingredients.error_code else "unknown"
        ),
        ingredient_coverage=review.ingredient_coverage if verified else "unknown",
        ingredient_evidence_id=review.evidence_id if verified else None,
        ingredient_source_version=review.source_version if verified else None,
        ingredient_error=row.ingredients.error_code,
    )


def _option_identities(row):
    if not _reviewed(row):
        return set()
    return {
        (i.identity.mfds_ingredient_id, i.identity.source_hash)
        for i in row.ingredients.review.ingredients
        if i.identity is not None
    }


async def _ranking(catalog, scope, rows):
    identities = {row.option_id: _option_identities(row) for row in rows}
    keys = sorted(set().union(*identities.values()))[:64]
    if not keys:
        return "not_found", {}, {}
    status, claims = await _claims(
        catalog,
        ClaimLookup(
            use="rank",
            context=scope,
            ingredients=[ClaimIngredientKey(mfds_ingredient_id=i, source_hash=h) for i, h in keys],
        ),
    )
    by_option = {}
    for option_id, ingredients in identities.items():
        by_option[option_id] = [
            claim
            for claim in claims
            if (claim.ingredient.mfds_ingredient_id, claim.ingredient.source_hash) in ingredients
        ]
    return status, {claim.publication_id: claim for claim in claims}, by_option


def _option_text(words, row, checked, basis, ordinal, matched_claims):
    price, collected = row.price, row.price.collected
    current = price.current_sale_price_krw
    amount = f"{current:,} KRW" if current is not None else words["unknown"]
    text = (
        f"{ordinal}. {row.product_name} · {row.option_name or row.option_id}\n"
        f"{words['current']} {amount}"
    )
    if basis == "collected_sale":
        captured = collected.sale_price_krw if collected else None
        amount = f"{captured:,} KRW" if captured is not None else words["unknown"]
        text += f"\n{words['collected']} {amount}"
        if collected and collected.collected_at_raw:
            text += f" ({collected.collected_at_raw})"
    if matched_claims:
        names = ", ".join(dict.fromkeys(claim.ingredient_name for claim in matched_claims))
        text += f"\n{words['contains']} · {names}"
    for condition in checked.ingredient_conditions:
        if condition.verdict in {"MATCH", "NOT_MATCH"}:
            present = (condition.verdict == "MATCH") == (condition.operator == "includes")
            finding = words["contains" if present else "absent"]
        else:
            finding = words["condition_error" if condition.verdict == "ERROR" else "unknown"]
        text += f"\n{condition.ingredient_name} · {finding}"
    return text


async def recommend_options(req, plan, catalog, previous):
    words = TEXT[req.locale]
    filters = _effective_filters(req.chat_context, plan)
    dependent = plan.intent in {"refine", "price", "detail"} or plan.scope == "previous"
    prior = previous if dependent else None
    require_in_stock = plan.require_in_stock
    if require_in_stock is None:
        require_in_stock = bool(prior and prior.require_in_stock)
    scope = _scope(req, plan, prior, for_option=True)
    basis = "current_sale"
    if (
        plan.option_price_basis == "collected_sale"
        and CAPTURED_PRICE.search(req.message)
        and not CURRENT_PRICE.search(req.message)
    ):
        basis = "collected_sale"
    elif (
        prior
        and not CURRENT_PRICE.search(req.message)
        and plan.intent != "price"
        and plan.option_price_basis != "current_sale"
    ):
        basis = prior.price_basis

    label = plan.option_category
    category = prior.category_id if prior else None
    scan = _Scan(stop="unsupported_category")
    if label:
        try:
            async with asyncio.timeout(CLAIM_DEADLINE):
                category = (
                    await _category(catalog, label) if _mentions(req.message, label) else None
                )
        except (UpstreamError, TimeoutError):
            category = None
            scan.failed, scan.stop = True, "category_lookup_failed"

    detail = plan.intent in {"detail", "price"}
    selections = None
    if detail or plan.scope == "previous":
        selections = prior.selections if prior else {}
        ids = req.chat_context.candidate_ids if req.chat_context else []
        if detail and plan.selection != "lowest_price":
            pid = (
                ids[plan.ordinal - 1]
                if plan.ordinal and plan.ordinal <= len(ids)
                else None
                if plan.ordinal
                else (req.chat_context.selected_product_id if req.chat_context else None)
            )
            if not pid and not plan.ordinal and len(ids) == 1:
                pid = ids[0]
            if not pid or pid not in selections:
                return (
                    ChatResponse(
                        answer=words["select"],
                        products=[],
                        result_type="clarification",
                        chat_context=req.chat_context,
                    ),
                    ToolResult(
                        tool="option_search", status="clarification", reason="option_required"
                    ),
                )
            selections = {pid: selections[pid]}

    conditions = {_normalized(c.ingredient_name): c for c in filters.ingredient_conditions}
    if detail:
        conditions.update({_normalized(c.ingredient_name): c for c in _plan_conditions(plan)})
    if len(conditions) > 6 or filters.max_price_krw == 0:
        raise ApiError(422, "Invalid option search conditions", "invalid_option_conditions")
    lookup = None
    if category:
        lookup = OptionLookup(
            category_id=category,
            price_basis=basis,
            max_price_krw=filters.max_price_krw,
            ingredient_conditions=[
                OptionFilter.model_validate(c.model_dump()) for c in conditions.values()
            ],
        )
        scan = await _scan(catalog, lookup, selections)
    evaluations = [_evaluation(row, lookup, filters, require_in_stock) for row in scan.rows]
    if scan.stop == "unsupported_category":
        status = "unsupported_category"
    elif scan.failed or any(e.verdict == "ERROR" for e in evaluations):
        status = "partial_failure"
    elif not scan.exhaustive:
        status = "search_incomplete"
    elif any(e.verdict == "MATCH" for e in evaluations):
        status = "matches"
    elif any(e.verdict == "UNKNOWN" for e in evaluations):
        status = "unconfirmed"
    else:
        status = "no_matches"
    checks = {item.option_id: item for item in evaluations}
    matches = {e.option_id for e in evaluations if e.verdict == "MATCH"}
    eligible = [row for row in scan.rows if row.option_id in matches]
    if detail and plan.selection != "lowest_price":
        eligible = scan.rows
    elif detail:

        def amount(row):
            if basis == "current_sale":
                return row.price.current_sale_price_krw
            return row.price.collected.sale_price_krw if row.price.collected else None

        eligible = sorted((row for row in eligible if amount(row) is not None), key=amount)[:1]
        if not eligible and status == "matches":
            status = "unconfirmed"
    claim_status, citations, by_option = await _ranking(catalog, scope, eligible)
    if selections is None:
        eligible.sort(
            key=lambda row: (-len(by_option.get(row.option_id, ())), row.product_id, row.option_id)
        )
    elif not detail:
        eligible.sort(key=lambda row: list(selections).index(row.product_id))

    selected = {}
    for row in eligible:
        selected.setdefault(row.product_id, row)
        if len(selected) == MAX_CARDS:
            break
    links = [
        OptionClaimLink(
            publication_id=claim.publication_id,
            product_id=row.product_id,
            option_id=row.option_id,
            ingredient_evidence_id=row.ingredients.review.evidence_id,
            ingredient_source_version=row.ingredients.review.source_version,
        )
        for row in selected.values()
        for claim in by_option.get(row.option_id, [])
    ]
    published = [citations[key] for key in dict.fromkeys(link.publication_id for link in links)]
    if claim_status == "available" and not published:
        claim_status = "not_found"
    ctx = (
        req.chat_context.model_copy(update={"filters": filters})
        if detail and req.chat_context
        else _context(filters, list(selected), int(time.time()))
    )
    if detail and selected:
        ctx.selected_product_id = next(iter(selected))
    option_context = (
        prior
        if detail
        else OptionConversation(
            category_id=category,
            price_basis=basis,
            claim_context=scope,
            selections={pid: row.option_id for pid, row in selected.items()},
            require_in_stock=require_in_stock,
        )
        if category
        else None
    )
    text = [
        words[
            "detail"
            if detail and selected
            else ("incomplete" if status == "search_incomplete" else status)
        ]
    ]
    if status in {"partial_failure", "search_incomplete"} and detail and selected:
        text.append(words["partial_failure" if status == "partial_failure" else "incomplete"])
    if (
        status in {"matches", "partial_failure", "search_incomplete"}
        and not selected
        and any(e.verdict == "UNKNOWN" for e in evaluations)
    ):
        text.append(words["unconfirmed"])
    text.extend(
        _option_text(
            words,
            row,
            checks[row.option_id],
            basis,
            ctx.candidate_ids.index(row.product_id) + 1,
            by_option.get(row.option_id, []),
        )
        for row in selected.values()
    )
    if published:
        text += [words["research"], *map(_citation_text, published), words["limitation"]]
    elif selected:
        text.append(words["error" if claim_status == "unavailable" else "missing"])
    response = ChatResponse(
        answer="\n\n".join(text),
        chat_context=ctx,
        option_context=option_context,
        claim_context=scope,
        products=[
            ProductRef(
                id=pid,
                brand="",
                name=row.product_name,
                category=row.catalog_category,
                option_id=row.option_id,
                option_name=row.option_name,
            )
            for pid, row in selected.items()
        ],
        result_type="product_detail"
        if detail and selected
        else "recommendations"
        if selected
        else ("clarification" if status == "unsupported_category" else "empty"),
        option_search=OptionSearchResult(
            status=status,
            category_id=category,
            price_basis=basis,
            candidate_count=scan.total,
            scope=(
                "catalog"
                if selections is None
                else "selected_option"
                if detail and len(selections) == 1
                else "previous"
            ),
            evaluated_count=len(evaluations),
            pages=scan.pages,
            exhaustive=scan.exhaustive,
            stop_reason=scan.stop,
            evaluations=evaluations,
        ),
        claim_status=claim_status,
        published_claims=published,
        option_claim_links=links,
    )
    return response, ToolResult(
        tool="option_search",
        product_ids=list(selected),
        status="partial"
        if selected and status in {"partial_failure", "search_incomplete"}
        else "error"
        if status == "partial_failure"
        else "success",
        reason=scan.stop,
    )
