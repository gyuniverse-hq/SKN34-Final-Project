"""Shared, read-only parent. Existing specialists retain their typed payloads and tools.

This graph resumes conversational goals, not interrupted executions. G7 owns saving.
"""

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.core.errors import ApiError, UpstreamError
from app.schemas.chat import ChatResponse
from app.schemas.consultation_parent import ConsultationParent, ParentQuestion, ParentTask
from app.services import knowledge_service, owned_look_consultation_service
from app.services.style_recipe_service import NAMES, ORDER, execute_style

_EXPLAIN = re.compile(r"왜|원인|주의|원리|설명")
_EXPLANATION_WITHDRAWAL = re.compile(
    r"(?:설명|원인|주의점|원리)(?:은|는|을|를)?\s*(?:필요\s*없|빼|말고|하지\s*마|됐)"
)


def wants_explanation(message):
    # Remove only withdrawn clauses: an independent positive request still survives.
    clauses = re.split(r"[,.;!?]|(?:고|지만)\s+", message)
    return any(_EXPLAIN.search(c) and not _EXPLANATION_WITHDRAWAL.search(c) for c in clauses)


_STYLE_ONLY = re.compile(r"(?:상품|제품|추천)은?\s*(?:됐고|빼고|말고|필요\s*없고).*(?:순서|방법)")
_ANSWERS = {"없어": "없어", "없어요": "없어", "있어": "있어", "있어요": "있어"}


def restore_followup(req, parent):
    """Resolve only an explicit, single ownership answer to a server-owned question."""
    if parent is None:
        return req
    if parent.look and (
        req.style_context is None
        or (parent.look.kind, parent.look.look_id)
        != (req.style_context.kind, req.style_context.look_id)
    ):
        return req
    req._consultation_parent = parent
    question = parent.question
    answer = _ANSWERS.get(req.message.strip().rstrip(".!"))
    if question and question.input_key == "ownership" and question.zone and answer:
        name = dict(zip(ORDER, NAMES["ko"], strict=True))[question.zone]
        req = req.model_copy(update={"message": f"{name}는 {answer}. 추가 추천해줘."})
    return req


def accept_task(parent, task, plan_id):
    if plan_id != parent.plan_id or task.version != parent.version:
        raise ValueError("Stale parent result")
    parent.tasks = [t for t in parent.tasks if t.goal != task.goal] + [task]


async def run_parent(
    req, kind, execute: Callable[[], Awaitable[ChatResponse]], *, catalog=None, trace=None
):
    previous = req._consultation_parent
    if previous and (kind == "skin") != any(t.goal == "skin" for t in previous.tasks):
        previous = None
    parent = previous.model_copy(deep=True) if previous else ConsultationParent()
    if previous:
        parent.version += 1
    parent.question = None
    parent.look = req.style_context
    events = trace if trace is not None else []
    response = None
    specialist_trace = []
    explanation_requested = kind == "owned_look" and wants_explanation(req.message)

    class State(TypedDict):
        next_goal: str

    def plan(_state):
        if _EXPLANATION_WITHDRAWAL.search(req.message) and not explanation_requested:
            for task in parent.tasks:
                if task.goal == "knowledge":
                    task.status = "superseded"
        if kind == "style":
            for task in parent.tasks:
                if task.goal == "owned_look":
                    task.status = "superseded"
        accept_task(
            parent,
            ParentTask(goal=kind, objective=req.message, version=parent.version),
            parent.plan_id,
        )
        return {"next_goal": kind}

    async def work(state):
        nonlocal response
        goal = state["next_goal"]
        task = next(t for t in parent.tasks if t.goal == goal)
        inputs = {"question": req.message}
        try:
            if goal == "knowledge":
                recipe = response.style_recipe
                # Recipe data resolves the user's reference; it is NOT G5 source evidence.
                binding = (
                    {"styleRecipe": recipe.model_dump(mode="json", by_alias=True)}
                    if recipe is not None
                    else {}
                )
                inputs["referenceContext"] = binding
                if recipe:
                    task.input_refs = [f"owned_look:{parent.version}:styleRecipe"]
                    task.reference_digest = hashlib.sha256(
                        recipe.model_dump_json().encode()
                    ).hexdigest()
                consultation = await knowledge_service.consult_knowledge(
                    req.message,
                    prior_user_context=json.dumps(binding, ensure_ascii=False) if binding else "",
                )
                response = response.model_copy(
                    update={
                        "answer": response.answer + "\n\n" + consultation.answer,
                        "knowledge": consultation.reply,
                    }
                )
                task.status = {
                    "answered": "completed",
                    "partial": "partial",
                    "insufficient_evidence": "partial",
                    "error": "failed",
                }[consultation.reply.status]
                task.result_refs = [e.id for e in consultation.reply.evidence]
                task.limitations = (
                    [consultation.reply.limitations] if consultation.reply.limitations else []
                )
            else:
                if kind == "owned_look":
                    response = await owned_look_consultation_service.execute_owned_look(
                        req, catalog, trace=specialist_trace
                    )
                else:
                    response = await execute()
                if response is None:
                    raise ValueError("Accepted parent task returned no response")
                task.status = "partial"
                if response.result_type == "clarification":
                    task.status = "waiting_user"
                    parent.question = ParentQuestion(
                        goal=kind,
                        version=parent.version,
                        text=response.answer,
                        input_key="situation"
                        if kind == "skin"
                        else "consent"
                        if req._consultation_memories is None
                        else "selection",
                    )
                if response.style_recipe:
                    recipe = response.style_recipe
                    task.result_refs = [recipe.recipe_id, recipe.recipe_version]
                    task.status = "completed" if kind == "style" and recipe.steps else task.status
                if response.style_status == "error":
                    task.status = "failed"
                if kind == "owned_look":
                    coverage = next(
                        (
                            e["result"]["coverage"]
                            for e in specialist_trace
                            if e["task"]["taskId"] == "N1"
                        ),
                        [],
                    )
                    unknown = [c for c in coverage if c["status"] == "ownership_unknown"]
                    if unknown:
                        zone = unknown[0]["zone"]
                        name = dict(zip(ORDER, NAMES["ko"], strict=True))[zone]
                        text = f"{name} 제품을 가지고 있나요?"
                        parent.question = ParentQuestion(
                            goal=kind,
                            version=parent.version,
                            text=text,
                            input_key="ownership",
                            zone=zone,
                        )
                        names = dict(zip(ORDER, NAMES["ko"], strict=True))
                        aggregate = (
                            "추가로 필요한지 확인할게요. "
                            + ", ".join(names[c["zone"]] for c in unknown)
                            + " 제품도 가지고 있나요?"
                        )
                        response.answer = response.answer.replace(aggregate, text)
                        task.status = "waiting_user"
                    elif (
                        coverage
                        and all(c["status"] == "fulfilled" for c in coverage)
                        or (
                            coverage
                            and not any(
                                c["status"] in {"evidence_missing", "ownership_unknown"}
                                for c in coverage
                            )
                            and response.products
                            and not response.owned_look_options
                        )
                    ):
                        task.status = "completed"
                if response.knowledge and kind == "skin":
                    task.result_refs += [e.id for e in response.knowledge.evidence]
                if kind == "skin" and response.compound:
                    task.limitations = list(response.compound.limitations)
                    if (
                        not task.limitations
                        and response.knowledge
                        and response.knowledge.status == "answered"
                    ):
                        task.status = "completed"
        except (UpstreamError, ApiError, TimeoutError):
            task.status = "failed"
            task.limitations = ["specialist_unavailable"]
            if response is None:
                response = ChatResponse(
                    answer="요청한 자료를 조회하지 못했어요. 다시 시도해 주세요.", products=[]
                )
            else:
                response.answer += (
                    "\n추가 설명 자료를 조회하지 못했어요. 확인한 상품 결과는 유지했어요."
                )
        accept_task(parent, task, parent.plan_id)
        events.append(
            {
                "planId": str(parent.plan_id),
                "planVersion": parent.version,
                "task": task.model_dump(mode="json", by_alias=True),
                "inputs": inputs,
                "specialistTrace": list(specialist_trace) if goal == "owned_look" else [],
            }
        )
        return {}

    def assess(state):
        if state["next_goal"] == "owned_look":
            recipe = response.style_recipe
            digest = (
                hashlib.sha256(recipe.model_dump_json().encode()).hexdigest() if recipe else None
            )
            for task in parent.tasks:
                if "owned_look" in task.depends_on and task.reference_digest != digest:
                    task.status = "superseded"
        if state["next_goal"] == "owned_look" and explanation_requested:
            # A requested independent explanation survives missing recipe/product evidence.
            accept_task(
                parent,
                ParentTask(
                    goal="knowledge",
                    objective=req.message,
                    version=parent.version,
                    depends_on=["owned_look"] if response.style_recipe else [],
                ),
                parent.plan_id,
            )
            return {"next_goal": "knowledge"}
        return {"next_goal": ""}

    graph = StateGraph(State)
    graph.add_node("plan", plan)
    graph.add_node("execute", work)
    graph.add_node("assess", assess)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "assess")
    graph.add_conditional_edges("assess", lambda s: "execute" if s["next_goal"] else END)
    # Existing G8 request budget; each closed goal executes once. No new retry/LLM loop.
    try:
        async with asyncio.timeout(get_settings().g8_deadline_seconds):
            await graph.compile(checkpointer=False).ainvoke({"next_goal": kind})
    except TimeoutError:
        for task in parent.tasks:
            if task.status == "pending":
                task.status = "failed"
                task.limitations = ["parent_deadline"]
        if response is None:
            response = ChatResponse(
                answer="조회 시간이 길어졌어요. 다시 시도해 주세요.", products=[]
            )
        else:
            response.answer += "\n추가 조회 시간이 초과되어 확인한 결과까지만 안내해 드려요."
    response._consultation_parent = parent
    response._parent_trace = events
    return response


async def try_owned_look(req, catalog):
    if not get_settings().g8_enabled:
        return None
    previous = req._consultation_parent
    style_only = bool(
        previous
        and previous.look
        and req.style_context
        and (previous.look.kind, previous.look.look_id)
        == (req.style_context.kind, req.style_context.look_id)
        and any(t.goal in {"owned_look", "style"} for t in previous.tasks)
        and not any(t.goal == "skin" for t in previous.tasks)
        and _STYLE_ONLY.search(req.message)
    )
    if style_only and not owned_look_consultation_service._STATE_REQUEST.search(req.message):

        async def style():
            response, _ = await execute_style(req, catalog)
            response.products = []
            return response

        result = await run_parent(req, "style", style)
        result._owned_look_context = req._owned_look_context
        return result
    if not owned_look_consultation_service.may_consult_owned_look(req):
        return None

    async def owned():
        return await owned_look_consultation_service.execute_owned_look(req, catalog)

    return await run_parent(req, "owned_look", owned, catalog=catalog)
