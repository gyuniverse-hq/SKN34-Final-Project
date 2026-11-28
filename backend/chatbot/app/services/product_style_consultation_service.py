"""Product comparison and look search share a parent, not recursive conversation saves."""

import hashlib
import json
import re

from app.core.config import get_settings
from app.schemas.chat import ChatResponse
from app.schemas.consultation_parent import ParentQuestion
from app.schemas.product_style_consultation import ProductStyleContext
from app.services.beauty_consultation_service import (
    direct_comparison,
    execute_beauty,
    interpret_beauty,
)
from app.services.consultation_parent_graph import run_independent_reads
from app.services.style_search_service import search_style

_WRITES = re.compile(r"발라|적용|설정|조절|기억|저장|삭제|장바구니|결제|\bAR\b", re.I)
_RETRY = re.compile(
    r"(?:(?:실패한|안 된|못 찾은)\s*)?(?:룩|스타일)(?:만|은|을)?\s*"
    r"(?:다시|재시도)(?:\s*(?:찾아|검색해|추천해|해))?\s*줘[.!]?"
)
_DISPLAY = {
    "answer",
    "products",
    "result_type",
    "evidence",
    "ingredient_results",
    "ingredient_comparison",
    "style_candidates",
    "style_conditions",
    "style_status",
}


def scope_digest(req):
    beauty = req.chat_context
    scope = {
        "product": beauty.selected_product_id if beauty else None,
        "option": beauty.selected_option_id if beauty else None,
        "filters": beauty.filters.model_dump(mode="json") if beauty else None,
        "style": req.style_context.model_dump(mode="json") if req.style_context else None,
        "conditions": [c.model_dump(mode="json") for c in req.style_conditions or []],
        "screenProduct": req.screen_context.product_id
        if req.screen_context
        else beauty.selected_product_id
        if beauty
        else None,
        "screenOption": req.screen_context.option_id
        if req.screen_context
        else beauty.selected_option_id
        if beauty
        else None,
    }
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()


def may_product_style(req):
    intent = req._parent_intent
    if intent and intent.action == "delegate":
        return False
    if (
        req._product_style_context
        and req._parent_replan
        and set(req._parent_replan["updated"]) <= {"product", "style"}
    ):
        return True
    if (
        intent
        and intent.action in {"retry", "resume"}
        and req._product_style_context
        and set(intent.targets) <= {"product", "style"}
    ):
        return True
    if (
        not get_settings().g8_enabled
        or req.locale != "ko"
        or req.request_type not in {"chat", "beauty_consultation", "style_consultation"}
        or req.ar_context
        or _WRITES.search(req.message)
    ):
        return False
    return bool(
        (req._product_style_context and _RETRY.fullmatch(req.message.strip()))
        or (
            re.search(r"비교", req.message)
            and re.search(r"룩|스타일", req.message)
            and re.search(r"찾|추천|검색", req.message)
        )
    )


async def try_product_style(req, catalog, llm):
    if not may_product_style(req):
        return None
    previous = req._product_style_context
    intent = req._parent_intent
    replanning = bool(previous and req._parent_replan)
    retry = bool(
        previous
        and (
            _RETRY.fullmatch(req.message.strip())
            or (intent and intent.action in {"retry", "resume"})
        )
    )
    initial = bool(
        re.search(r"비교", req.message)
        and re.search(r"룩|스타일", req.message)
        and re.search(r"찾|추천|검색", req.message)
    )
    if not initial and not retry and not replanning:
        return None
    if (retry or replanning) and previous.scope_digest != scope_digest(req):
        return ChatResponse(
            answer="상담 조건이 바뀌었어요. 비교할 상품과 찾을 룩을 다시 알려주세요.",
            products=[],
            result_type="clarification",
        )
    if (
        retry
        and intent is None
        and (previous.product_result is None or "product" in previous.failed)
    ):
        return ChatResponse(
            answer="상품 비교가 아직 확인되지 않았어요. 비교 대상부터 다시 알려주세요.",
            products=[],
            result_type="clarification",
        )
    objective = previous.objective if retry else req.message
    if replanning:
        objective = previous.objective + "\n현재 사용자의 변경 요청: " + req.message
    work_req = req.model_copy(deep=True, update={"message": objective, "style_search": False})
    cached = {}
    if retry or replanning:
        for goal, raw in [("product", previous.product_result), ("style", previous.style_result)]:
            if (
                raw is not None
                and goal not in previous.failed
                and not (intent and intent.action == "resume" and goal in intent.targets)
                and not (replanning and goal in req._parent_replan["invalidated"])
            ):
                cached[goal] = ChatResponse.model_validate(raw)

    catalog_calls = []

    class ObservedCatalog:
        def __init__(self, goal):
            self.goal = goal

        def __getattr__(self, name):
            method = getattr(catalog, name)

            async def call(*args, **kwargs):
                entry = {"task": self.goal, "tool": name, "args": list(args), "kwargs": kwargs}
                catalog_calls.append(entry)
                try:
                    result = await method(*args, **kwargs)
                    rows = result if isinstance(result, list) else [result]
                    entry["resultIds"] = [r.id for r in rows if hasattr(r, "id")]
                    entry["status"] = "success"
                    return result
                except Exception:
                    entry["status"] = "failed"
                    raise

            return call

    product_catalog = ObservedCatalog("product") if catalog is not None else None
    style_catalog = ObservedCatalog("style") if catalog is not None else None

    async def product():
        product_req = work_req.model_copy(deep=True)
        product_req._comparison_followup = True
        if replanning and "product" in req._parent_replan["updated"]:
            change = next(c for c in intent.changes if c.task_id == "product")
            product_req = work_req.model_copy(update={"message": change.quote})
            product_req._comparison_followup = True
        plan = await interpret_beauty(product_req, llm)
        if not direct_comparison(product_req, plan) and len(plan.compare_ordinals) != 2:
            return ChatResponse(
                answer="비교할 두 상품을 선택하거나 상품명을 알려주세요. "
                "브랜드 전체의 품질을 개별 상품 정보로 판단하지는 않아요.",
                products=[],
                result_type="clarification",
            )
        result = await execute_beauty(product_req, plan, product_catalog)
        return result or ChatResponse(
            answer="비교할 상품을 확인해 주세요.", products=[], result_type="clarification"
        )

    async def style():
        if (
            re.search(r"비슷|어울리", objective)
            and not work_req.style_context
            and not work_req.style_conditions
            and not work_req.previous_style_candidates
        ):
            return ChatResponse(
                answer="어떤 룩을 기준으로 찾을까요? 기준 룩이나 원하는 분위기를 알려주세요.",
                products=[],
                result_type="clarification",
                style_status="clarification",
            )
        # The original instruction and server-restored style reference reach the real Tool.
        style_req = work_req
        if work_req.style_context and catalog is not None:
            reference = await style_catalog.get_style_look(
                work_req.style_context.kind, work_req.style_context.look_id
            )
            if reference is None or reference.id != work_req.style_context.look_id:
                return ChatResponse(
                    answer="기준 룩을 다시 선택해 주세요.",
                    products=[],
                    result_type="clarification",
                    style_status="clarification",
                )
            style_req = work_req.model_copy(
                update={"message": objective + "\n사용자가 선택한 기준 룩 제목: " + reference.title}
            )
        return await search_style(style_req, style_catalog, llm)

    task_results = []

    def task_inputs(goal):
        return {
            "objective": objective,
            "scopeDigest": scope_digest(req),
            "catalogRequests": [
                {k: entry[k] for k in ("tool", "args", "kwargs")}
                for entry in catalog_calls
                if entry["task"] == goal
            ],
        }

    parent, results, trace = await run_independent_reads(
        objective,
        {"product": product, "style": style},
        cached,
        previous=req._consultation_parent if retry or replanning else None,
        task_results=task_results,
        task_inputs=task_inputs,
        deadline=req._parent_deadline,
        selected=(set(req._parent_replan["invalidated"]) - set(req._parent_replan["withdrawn"]))
        if replanning
        else set(intent.targets)
        if retry and intent and intent.action in {"retry", "resume"}
        else None,
    )
    parts = []
    for task in parent.tasks:
        if task.goal == "product":
            task.product_operation = "compare"
        result = results.get(task.goal)
        if result is not None:
            parts.append(result.answer)
        if task.status == "failed":
            label = "상품 비교" if task.goal == "product" else "룩 검색"
            notice = f"{label}은 이번 요청에서 확인하지 못했어요."
            if any(t.status == "completed" for t in parent.tasks):
                notice += " 다른 작업에서 확인한 내용은 유지했어요."
            parts.append(notice)
    base = results.get("product") or ChatResponse(answer="", products=[])
    response = base.model_copy(deep=True, update={"answer": "\n\n".join(parts)})
    response.style_context = req.style_context
    # Informational comparison must not clear the server-owned selection merely
    # because G7 deliberately does not restore executable candidate sessions.
    response.chat_context = req.chat_context
    style_result = results.get("style")
    if style_result:
        response.style_candidates = style_result.style_candidates
        response.style_conditions = style_result.style_conditions
        response.style_status = style_result.style_status
    elif any(t.goal == "style" and t.status == "failed" for t in parent.tasks):
        response.style_status = "error"
    response._task_results = task_results
    response._consultation_parent = parent
    response._parent_trace = trace
    response._parent_trace.append({"catalogCalls": catalog_calls})
    if req._parent_intent_audit:
        response._parent_trace.append({"parentIntent": req._parent_intent_audit})
    # No session token, AR capability, memory proposal or arbitrary service object is stored.
    snapshots = {
        goal: result.model_dump(mode="json", by_alias=True, include=_DISPLAY)
        for goal, result in results.items()
    }
    from app.services.consultation_parent_graph import task_scope

    saved_scope = req.model_copy(
        update={
            "chat_context": response.chat_context,
            "style_conditions": response.style_conditions,
        }
    )
    for task in parent.tasks:
        task.display_result = snapshots.get(task.goal)
        task.scope_digest = task_scope(saved_scope)
        if task.status == "waiting_user" and task.goal == "product":
            parent.question = ParentQuestion(
                comparison_price_basis=results[task.goal]._comparison_price_basis,
                comparison_base_id=results[task.goal]._comparison_base_id,
                comparison_choices=results[task.goal]._comparison_choices,
                task_id=task.task_id,
                goal="product",
                version=parent.version,
                text=results[task.goal].answer,
                input_key="selection",
            )
    response._product_style_context = ProductStyleContext(
        objective=objective,
        scope_digest=scope_digest(saved_scope),
        product_result=snapshots.get("product"),
        style_result=snapshots.get("style"),
        failed=[t.goal for t in parent.tasks if t.status != "completed"],
    )
    return response
