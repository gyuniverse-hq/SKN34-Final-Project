"""Shared, read-only parent. Existing specialists retain their typed payloads and tools.

This graph resumes conversational goals, not interrupted executions. G7 owns saving.
"""

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import TypedDict
from uuid import uuid4

import httpx
from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.core.errors import ApiError, UpstreamError
from app.schemas.chat import BeautyContext, ChatResponse
from app.schemas.consultation_parent import (
    ConsultationParent,
    ParentQuestion,
    ParentTask,
    ResultSelection,
)
from app.schemas.consultation_task import ConsultationTaskRequest
from app.services import knowledge_service, owned_look_consultation_service
from app.services.consultation_answer_service import finalize_answer
from app.services.consultation_task_adapter import adapt_independent, fingerprint, validate_results
from app.services.style_recipe_service import NAMES, ORDER, execute_style

_EXPLAIN = re.compile(r"왜|원인|주의|원리|설명")
_EXPLANATION_WITHDRAWAL = re.compile(
    r"(?:설명|원인|주의점|원리)(?:은|는|을|를)?\s*(?:필요\s*없|빼|말고|하지\s*마|됐)"
)


def wants_explanation(message):
    # Remove only withdrawn clauses: an independent positive request still survives.
    clauses = re.split(r"[,.;!?]|(?:고|지만)\s+", _EXPLANATION_WITHDRAWAL.sub("", message))
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
    if not get_settings().g8_enabled or parent.execution_state == "cancelled":
        return req
    question = parent.question
    answer = _ANSWERS.get(req.message.strip().rstrip(".!"))
    if question and question.input_key == "ownership" and question.zone and answer:
        name = dict(zip(ORDER, NAMES["ko"], strict=True))[question.zone]
        if question.need_id and question.recipe_version:
            if not question.task_id or not question.task_id.startswith("task-"):
                req = req.model_copy(update={"message": f"{name} 상품 확인 답변. 추가 추천해줘."})
            req._owned_look_answer = (
                question.need_id,
                question.recipe_version,
                answer,
                question.ownership_scope or "legacy",
            )
        else:
            # Compatibility with stored questions predating product-level targets.
            req = req.model_copy(update={"message": f"{name}는 {answer}. 추가 추천해줘."})
    return req


def accept_task(parent, task, plan_id):
    if plan_id != parent.plan_id or task.version != parent.version:
        raise ValueError("Stale parent result")
    parent.tasks = [t for t in parent.tasks if t.task_id != task.task_id] + [task]


async def execute_request(
    parent, task, request, operation, *, retries=0, classify=True, check_active=None
):
    """One execution boundary for all parent reads. Callbacks never grant write rights."""
    if check_active:
        await check_active()
    if task.version != parent.version or request.task_id != task.task_id:
        raise ValueError("Stale or mismatched execution request")
    if request.capability != task.goal:
        raise ValueError("Execution capability mismatch")
    tasks = {t.task_id: t for t in parent.tasks}
    for source in request.depends_on:
        if source not in tasks or tasks[source].version != parent.version:
            raise ValueError("Missing or stale execution dependency")
        missing_binding = (
            "referenceContext" in request.inputs and not request.inputs["referenceContext"]
        )
        if missing_binding or (request.requires_success and tasks[source].status != "completed"):
            task.status = "partial"
            task.reason = "dependency_unavailable"
            task.limitations = [task.reason]
            return None, False
    digest = fingerprint(request.inputs)
    task.attempts += 1
    if task.goal == "product":
        # A new read cannot carry the previous read's success assessment through failure.
        task.product_assessment = None
    task.tool_trace_ids.append(f"{parent.plan_id}:{parent.version}:{task.task_id}:{task.attempts}")
    try:
        result = await operation()
        if check_active:
            await check_active()
        if fingerprint(request.inputs) != digest:
            raise ValueError("Execution inputs mutated")
        if classify:
            if result is None:
                raise ValueError("Missing read result")
            validate_results(result._task_results)
            task.status = "waiting_user" if result.result_type == "clarification" else "completed"
            if result.style_status in {"error", "unsupported"}:
                task.status = "failed" if result.style_status == "error" else "partial"
            if task.goal == "knowledge" and result.knowledge:
                task.status = {
                    "answered": "completed",
                    "partial": "partial",
                    "insufficient_evidence": "partial",
                    "error": "failed",
                }[result.knowledge.status]
            if task.goal == "owned_look" and result._owned_look_outcome:
                task.status = result._owned_look_outcome.status
            if task.goal == "skin" and result.result_type != "clarification":
                task.status = "partial"
                if (
                    result.compound
                    and not result.compound.limitations
                    and result.knowledge
                    and result.knowledge.status == "answered"
                    and not result.knowledge.limitations
                ):
                    task.status = "completed"
            if task.goal == "skin" and result.chat_context and result.chat_context.compound:
                task.compound_context = result.chat_context.compound.model_copy(deep=True)
            task.result_refs = [p.id for p in result.products]
            task.result_refs += [f"{c.kind}:{c.look_id}" for c in result.style_candidates or []]
            task.reason = None
            task.limitations = []
            if task.goal == "product":
                from app.services.product_search_contract import missing_assessment

                assessment = result._product_assessment
                if assessment is None and task.status != "waiting_user":
                    assessment = missing_assessment(task.product_requirement)
                if assessment is not None:
                    task.product_assessment = assessment
                    task.product_requirement = assessment.requirement
                    task.status = assessment.status
                    task.reason = assessment.outcome
                    task.limitations = list(assessment.limitations)
                if result.chat_context is not None:
                    task.product_context = result.chat_context.model_dump(
                        mode="json", by_alias=True, exclude={"session", "compound"}
                    )
        return result, False
    except (ApiError, UpstreamError, TimeoutError) as exc:
        if isinstance(exc, ApiError) and exc.code == "request_interrupted":
            raise
        task.status = "failed"
        task.reason = exc.code if isinstance(exc, ApiError) else "upstream_unavailable"
        task.limitations = [task.reason or "upstream_unavailable"]
        cause = exc
        transient = not isinstance(exc, ApiError) or (
            exc.status in {502, 503, 504} and exc.code != "g5_disabled"
        )
        while cause is not None:
            if isinstance(cause, httpx.HTTPStatusError):
                transient = cause.response.status_code in {429, 502, 503, 504}
                break
            if isinstance(cause, (ValueError, TypeError)):
                transient = False
                break
            cause = cause.__cause__
        return None, transient and task.attempts <= retries


async def run_independent_reads(
    objective,
    operations,
    cached,
    *,
    previous=None,
    task_results=None,
    task_inputs=None,
    selected=None,
    deadline=None,
    requests=None,
    bind_inputs=None,
    check_active=None,
):
    """E01: keep completed reads; retry only a failed transient read within one budget."""
    parent = ConsultationParent(
        plan_id=previous.plan_id if previous else ConsultationParent().plan_id,
        version=previous.version + 1 if previous else 1,
    )
    results = dict(cached)
    events = []
    goals = list(operations)
    if requests:
        ordered = []
        while len(ordered) < len(goals):
            ready = [
                key
                for key in goals
                if key not in ordered and set(requests[key].depends_on) <= set(ordered)
            ]
            if not ready:
                raise ValueError("Missing dependency or cyclic task plan")
            ordered.extend(ready)
        goals = ordered
    for goal in goals:
        prior = next((t for t in previous.tasks if t.task_id == goal), None) if previous else None
        parent.tasks.append(
            ParentTask(
                task_id=goal,
                product_operation=prior.product_operation if prior else None,
                product_requirement=prior.product_requirement if prior else None,
                product_assessment=prior.product_assessment if prior else None,
                product_context=prior.product_context if prior else None,
                input_needs=list(prior.input_needs) if prior else [],
                compound_context=prior.compound_context if prior else None,
                goal=requests[goal].capability if requests else goal,
                depends_on=list(requests[goal].depends_on) if requests else [],
                explanation_quote=prior.explanation_quote if prior else "",
                objective=requests[goal].inputs.get("objective", objective)
                if requests
                else objective,
                version=parent.version,
                status=(prior.status if prior else "completed")
                if goal in cached
                else prior.status
                if selected is not None and goal not in selected and prior
                else "pending",
                reason="preserved_completed_result" if goal in cached else None,
                input_refs=[f"{previous.plan_id}:{previous.version}:{goal}"]
                if goal in cached and previous
                else [],
                result_refs=list(prior.result_refs)
                if prior and (goal in cached or (selected is not None and goal not in selected))
                else [],
            )
        )

    class ReadState(TypedDict):
        index: int
        retry: bool

    async def execute(state):
        task = parent.tasks[state["index"]]
        if task.task_id in results:
            return {"retry": False}
        if selected is not None and task.task_id not in selected:
            return {"retry": False}
        if bind_inputs:
            bind_inputs(task.task_id, results, requests[task.task_id])
        result, retry = await execute_request(
            parent,
            task,
            requests[task.task_id]
            if requests
            else ConsultationTaskRequest(
                task_id=task.task_id, capability=task.goal, inputs={"objective": objective}
            ),
            operations[task.task_id],
            retries=get_settings().g8_read_retries,
            check_active=check_active,
        )
        if result is not None:
            results[task.task_id] = result
        events.append(
            {
                "planId": str(parent.plan_id),
                "planVersion": parent.version,
                "task": task.model_dump(mode="json", by_alias=True),
                "input": {"objective": objective},
                "result": results[task.task_id].model_dump(
                    mode="json",
                    by_alias=True,
                    exclude={"chat_context", "conversation", "memory_proposal", "ar_result"},
                )
                if task.task_id in results
                else None,
            }
        )
        return {"retry": retry}

    def assess(state):
        return {"index": state["index"] if state["retry"] else state["index"] + 1}

    graph = StateGraph(ReadState)
    graph.add_node("execute", execute)
    graph.add_node("assess", assess)
    graph.add_edge(START, "execute")
    graph.add_edge("execute", "assess")
    graph.add_conditional_edges("assess", lambda s: "execute" if s["index"] < len(goals) else END)
    try:
        budget = max(0, deadline - monotonic()) if deadline else get_settings().g8_deadline_seconds
        async with asyncio.timeout(budget):
            await graph.compile(checkpointer=False).ainvoke(
                {"index": 0, "retry": False},
                config={
                    "recursion_limit": 2 * len(goals) * (get_settings().g8_read_retries + 1) + 1
                },
            )
    except TimeoutError:
        for task in parent.tasks:
            if task.status == "pending" or (
                task.status == "failed" and task.task_id not in results
            ):
                task.status = "failed"
                task.reason = "deadline_exceeded"
                task.limitations = ["deadline_exceeded"]
        events.append({"reason": "deadline_exceeded", "planId": str(parent.plan_id)})
    records = validate_results(
        [
            adapt_independent(
                parent,
                task,
                results.get(task.task_id),
                task_inputs(task.task_id) if task_inputs else {"objective": objective},
            )
            for task in parent.tasks
        ]
    )
    if task_results is not None:
        task_results.extend(records)
    for task, record in zip(parent.tasks, records, strict=True):
        task.input_needs = list(record.missing_inputs)
    return parent, results, events


# Only display data is persisted. Session tokens, execution capabilities, memory
# proposals and arbitrary internal objects must never enter a per-task snapshot.
TASK_DISPLAY_FIELDS = {
    "answer",
    "products",
    "result_type",
    "knowledge",
    "evidence",
    "ingredient_results",
    "ingredient_comparison",
    "style_candidates",
    "style_conditions",
    "style_status",
    "style_recipe",
    "option_search",
    "owned_look_options",
    "compound",
}


def task_scope_components(req, task=None, *, legacy=False):
    from app.services.consultation_memory import ignores_memory

    beauty = req.chat_context
    # Each task owns its filters. A sibling's returned filters are not a scope change.
    catalog = {
        "product": beauty.selected_product_id if beauty else None,
        "option": beauty.selected_option_id if beauty else None,
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
    # A cached task's reference to its own earlier result is history, not a sibling input.
    source_refs = task and any(ref.rsplit(":", 1)[-1] != task.task_id for ref in task.input_refs)
    if not legacy and task and not task.depends_on and not source_refs:
        if task.goal == "style":
            catalog = {key: catalog[key] for key in ("style", "conditions")}
        elif task.goal == "product" and task.product_operation == "compare":
            catalog = {
                key: value for key, value in catalog.items() if key not in {"style", "conditions"}
            }
    values = {
        "catalog": catalog,
        "memoryEpoch": req._memory_epoch,
        "memoryGeneration": req._memory_generation,
        # None and an empty read contain no structured personal data. Consent/data
        # changes still invalidate via epoch, generation, opt-out and exact refs.
        "memoryAvailable": (
            req._consultation_memories is not None if legacy else bool(req._consultation_memories)
        ),
        "ignoreMemory": ignores_memory(req.message),
        "memoryRefs": sorted([str(m.id), m.version] for m in req._consultation_memories or ()),
    }
    if not legacy:
        values["version"] = 2
    return values


def task_scope(req, task=None):
    return fingerprint(task_scope_components(req, task))


def scope_matches(req, task):
    expected = task_scope(req, task)
    if task.scope_snapshot is not None:
        return (
            fingerprint(task.scope_snapshot) == task.scope_digest and task.scope_digest == expected
        )
    if task.scope_digest in {expected, task_scope(req)}:
        return True
    # Old snapshots contain only a digest. Reconstruct only exact legacy values;
    # an empty-read representation may differ, but no other fence may change.
    legacy = task_scope_components(req, legacy=True)
    if task.scope_digest == fingerprint(legacy):
        return True
    if not legacy["memoryRefs"]:
        legacy["memoryAvailable"] = not legacy["memoryAvailable"]
        return task.scope_digest == fingerprint(legacy)
    return False


async def run_id_tasks(req, dispatch):
    """New independent read goals and their subsequent ID-addressed operations."""
    check_active = getattr(req._g7_execution, "check_active", None)
    if check_active:
        await check_active()
    intent = req._parent_intent
    previous = req._consultation_parent
    if not intent or not previous:
        return None
    managed = {t.task_id for t in previous.tasks if t.task_id.startswith("task-")}
    if intent.action == "show" and set(intent.targets) <= managed:
        from app.services.consultation_intent_service import control_response

        chosen = [t for t in previous.tasks if t.task_id in intent.targets]
        if any(
            t.display_result is None
            or not scope_matches(req, t)
            or t.status in {"cancelled", "superseded", "failed"}
            for t in chosen
        ):
            return control_response(
                req, "결과를 다시 확인할 대상과 조건을 알려주세요.", clarification=True
            )
        parent = previous.model_copy(deep=True)
        parent.version += 1
        if parent.question:
            parent.question.version = parent.version
        for question in parent.pending_questions:
            question.version = parent.version
        if parent.result_selection:
            parent.result_selection.version = parent.version
        response = combine_id_results(
            parent,
            {t.task_id: ChatResponse.model_validate(t.display_result) for t in chosen},
            locale=req.locale,
            display_task_id=chosen[0].task_id if len(chosen) == 1 else None,
        )
        response.chat_context, response.style_context = req.chat_context, req.style_context
        response._consultation_parent = parent
        response._owned_look_context = req._owned_look_context
        response._product_style_context = req._product_style_context
        response._preserve_parent_context = True
        response._parent_trace = [
            {
                "displayTaskIds": intent.targets,
                "toolCalls": 0,
                "parentIntent": req._parent_intent_audit,
            }
        ]
        return response
    selected = set(intent.targets) if intent.action in {"retry", "resume"} else set()
    if req._parent_replan:
        selected |= set(req._parent_replan["invalidated"]) - set(req._parent_replan["withdrawn"])
    if not intent.additions and not (selected & managed):
        return None
    plan = previous.model_copy(deep=True)
    new_ids = []
    for addition in intent.additions:
        task_id = "task-" + uuid4().hex
        objective = addition.quote
        if addition.shared_quotes:
            objective += "\n공통 조건: " + " / ".join(addition.shared_quotes)
        plan.tasks.append(
            ParentTask(
                task_id=task_id,
                goal=addition.capability,
                objective=objective,
                explanation_quote=addition.explanation_quote,
                version=plan.version,
                product_operation=addition.product_operation,
            )
        )
        new_ids.append(task_id)
    selected.update(new_ids)
    # Revalidate after additions; the existing task-count bound must never truncate work.
    plan = ConsultationParent.model_validate(plan.model_dump())
    tasks = {t.task_id: t for t in plan.tasks}
    if intent.action in {"retry", "resume"} and any(
        tasks[task_id].scope_digest is not None and not scope_matches(req, tasks[task_id])
        for task_id in selected
        if task_id not in new_ids
    ):
        from app.services.consultation_intent_service import control_response

        return control_response(
            req, "선택한 상품이나 룩이 바뀌었어요. 이어갈 대상을 확인해 주세요.", clarification=True
        )
    cached, requests, operations, sources = {}, {}, {}, {}
    for task_id, task in tasks.items():
        if (
            task.display_result is not None
            and task_id not in selected
            and task.status in {"completed", "partial", "waiting_user"}
            and scope_matches(req, task)
        ):
            cached[task_id] = ChatResponse.model_validate(task.display_result)
        if task.display_result is not None and not scope_matches(req, task):
            task.display_result = None
            task.result_refs = []
            task.status = "superseded"
            task.reason = "scope_changed"
        if (
            task_id in selected
            and task_id not in new_ids
            and req._parent_replan
            and task_id in req._parent_replan["updated"]
        ):
            change = next(c for c in intent.changes if c.task_id == task_id)
            task.objective += "\n현재 변경 요청: " + change.quote
        requests[task_id] = ConsultationTaskRequest(
            task_id=task_id,
            capability=task.goal,
            inputs={
                "objective": task.objective,
                "scopeDigest": task_scope(req, task),
                "productRequirement": task.product_requirement.model_dump()
                if task.product_requirement
                else None,
                "productContext": task.product_context,
                "compoundContext": task.compound_context.model_dump(mode="json", by_alias=True)
                if task.compound_context
                else None,
                "productOperation": task.product_operation,
            },
            depends_on=list(task.depends_on),
            requires_success=not (
                task.goal == "knowledge"
                and all(
                    source in tasks and tasks[source].goal == "owned_look"
                    for source in task.depends_on
                )
            ),
        )

        async def call(current=task):
            child = req.model_copy(deep=True, update={"message": current.objective})
            child._question_answers = [
                (q, quote) for q, quote in req._question_answers if q.task_id == current.task_id
            ]
            if child._question_answers:
                quotes = [quote for _, quote in child._question_answers]
                quotes.extend(
                    c.quote
                    for c in intent.changes
                    if c.task_id == current.task_id and c.operation == "update"
                )
                child.message = "\n".join(dict.fromkeys(quotes))
            child._requested_explanation = current.explanation_quote
            child._parent_intent = None
            child._parent_replan = None
            child._parent_sources = sources.get(current.task_id, {})
            if current.goal == "skin":
                child._compound_context = current.compound_context
                update = next(
                    (
                        c
                        for c in intent.changes
                        if c.task_id == current.task_id and c.operation == "update"
                    ),
                    None,
                )
                if update and current.compound_context is not None:
                    # The saved goal is structured context, not another request to explain it.
                    child.message = update.quote
                elif update:
                    # Until a specialist goal exists, its original request still owns the reply.
                    child.message = current.objective
                # A delegated skin goal does not inherit the look screen's routing scope.
                child.request_type = "beauty_consultation"
                child.style_context = None
                child.style_search = None
                child.screen_context = None
            if current.goal == "product":
                if (
                    child._comparison_question
                    and child._comparison_question.task_id != current.task_id
                ):
                    child._comparison_question = None
                child._comparison_followup = current.product_operation == "compare"
                if child._comparison_followup and intent:
                    update = next(
                        (
                            c
                            for c in intent.changes
                            if c.task_id == current.task_id and c.operation == "update"
                        ),
                        None,
                    )
                    if update:
                        child.message = update.quote
                child._product_operation = current.product_operation
                child._product_contract_required = True
                child._product_requirement = current.product_requirement
                child.chat_context = (
                    BeautyContext.model_validate(current.product_context)
                    if current.product_context
                    else req.chat_context
                    if current.product_operation != "search"
                    else None
                )
                if current.product_operation == "search":
                    # A new search's references come from its own saved context, not
                    # the screen/operands that happened to open the consultation.
                    child.screen_context = None
                    child._product_style_context = None
            return await dispatch(current.goal, child)

        operations[task_id] = call
    records = []

    def bind(task_id, results, request):
        sources[task_id] = {key: results[key] for key in request.depends_on if key in results}
        if request.capability == "knowledge":
            recipes = [r.style_recipe for r in sources[task_id].values() if r.style_recipe]
            if len(recipes) > 1:
                raise ValueError("Ambiguous recipe input")
            request.inputs["referenceContext"] = (
                {"styleRecipe": recipes[0].model_dump(mode="json", by_alias=True)}
                if recipes
                else {}
            )

    parent, results, trace = await run_independent_reads(
        req.message,
        operations,
        cached,
        previous=plan,
        selected=selected,
        requests=requests,
        task_inputs=lambda task_id: requests[task_id].inputs,
        task_results=records,
        deadline=req._parent_deadline,
        bind_inputs=bind,
        check_active=check_active,
    )
    # Results propose read work; the parent authorizes source, goal and binding before execution.
    if check_active:
        await check_active()
    proposed = []
    continuation_limits = []
    for record in records:
        source_task = next(t for t in parent.tasks if t.task_id == record.task_id)
        source_result = results.get(record.task_id)
        for proposal in record.proposed_next_tasks:
            from app.services.consultation_task_adapter import validate_continuation

            reason = validate_continuation(parent, source_task, record, proposal, source_result)
            key = (proposal.capability, proposal.objective, record.task_id)
            duplicate = any(
                t.goal == proposal.capability
                and t.objective == proposal.objective
                and record.task_id in t.depends_on
                for t in parent.tasks
            ) or any(k == key for k, _, _ in proposed)
            if reason or duplicate or len(parent.tasks) + len(proposed) >= 5:
                if not duplicate:
                    source_task.status = "partial"
                    source_task.limitations.append(reason or "continuation_capacity")
                    continuation_limits.append(reason or "continuation_capacity")
                trace.append(
                    {
                        "continuation": "rejected",
                        "sourceTaskId": record.task_id,
                        "reason": reason or ("duplicate" if duplicate else "capacity"),
                    }
                )
                continue
            proposed.append((key, proposal, record.task_id))
    if proposed:
        follow_ids = set()
        for _, proposal, source_id in proposed:
            tid = "task-" + uuid4().hex
            task = ParentTask(
                task_id=tid,
                goal=proposal.capability,
                objective=proposal.objective,
                version=parent.version,
                depends_on=[source_id],
            )
            parent.tasks.append(task)
            tasks[tid] = task
            requests[tid] = ConsultationTaskRequest(
                task_id=tid,
                capability=proposal.capability,
                inputs={"objective": proposal.objective, "scopeDigest": task_scope(req, task)},
                depends_on=[source_id],
                requires_success=False,
            )

            async def continue_read(current=task):
                child = req.model_copy(deep=True, update={"message": current.objective})
                child._parent_intent = None
                child._parent_replan = None
                child._parent_sources = sources.get(current.task_id, {})
                return await dispatch(current.goal, child)

            operations[tid] = continue_read
            follow_ids.add(tid)
            trace.append(
                {
                    "continuation": "accepted",
                    "sourceTaskId": source_id,
                    "taskId": tid,
                    "sourceFingerprint": proposal.source_fingerprint,
                }
            )
        records.clear()
        parent, results, continuation_trace = await run_independent_reads(
            req.message,
            operations,
            results,
            previous=parent,
            selected=follow_ids,
            requests=requests,
            task_results=records,
            task_inputs=lambda tid: requests[tid].inputs,
            deadline=req._parent_deadline,
            bind_inputs=bind,
            check_active=check_active,
        )
        trace.extend(continuation_trace)
    reconcile_questions(parent, previous=previous, selected=selected)
    if intent.question.strip():
        parent.question = ParentQuestion(
            goal=parent.tasks[0].goal,
            version=parent.version,
            text=intent.question,
            input_key="selection",
        )
    parent.look = req.style_context
    for task in parent.tasks:
        source = tasks[task.task_id]
        task.depends_on = source.depends_on
        task.scope_snapshot = task_scope_components(req, task)
        task.scope_digest = fingerprint(task.scope_snapshot)
        result = results.get(task.task_id)
        task.display_result = (
            result.model_dump(mode="json", by_alias=True, include=TASK_DISPLAY_FIELDS)
            if result is not None
            else source.display_result
        )
    if continuation_limits:
        records[:] = validate_results(
            [
                adapt_independent(
                    parent, task, results.get(task.task_id), requests[task.task_id].inputs
                )
                for task in parent.tasks
            ]
        )
    response = combine_id_results(parent, results, previous=previous, locale=req.locale)
    if continuation_limits:
        response.answer += (
            "\n\n추가 설명을 이번 실행에서 마치지 못했어요. 확인된 결과는 유지했어요."
        )
    if parent.question:
        response.result_type = "clarification"
    if intent.question.strip():
        response.answer += "\n\n" + intent.question
        response.result_type = "clarification"
    response.chat_context = req.chat_context
    response.style_context = req.style_context
    response._consultation_parent = parent
    response._owned_look_context = req._owned_look_context
    for task_id, result in results.items():
        if task_id in selected and result._owned_look_context is not None:
            response._owned_look_context = result._owned_look_context
            response._owned_look_outcome = result._owned_look_outcome
        if task_id in selected and result.compound is not None and result.chat_context is not None:
            response.chat_context = result.chat_context
    response._product_style_context = req._product_style_context
    response._preserve_parent_context = True
    response._task_results = records
    response._parent_trace = [
        *trace,
        {
            "parentIntent": req._parent_intent_audit,
            "newTaskIds": new_ids,
            "selectedTaskIds": sorted(selected),
        },
    ]
    return response


def reconcile_questions(parent, *, previous=None, selected=()):
    """Retain each typed input need and focus one question without consuming siblings."""
    old = list(previous.pending_questions) if previous else []
    if previous and previous.question and previous.question not in old:
        old.append(previous.question)
    questions = []
    for task in parent.tasks:
        if task.status != "waiting_user":
            continue
        if task.task_id not in selected:
            preserved = [q for q in old if q.task_id == task.task_id]
            if preserved:
                questions.extend(
                    q.model_copy(update={"version": parent.version}) for q in preserved
                )
                continue
        for need in task.input_needs:
            details = need.model_dump(exclude={"key", "question"})
            questions.append(
                ParentQuestion(
                    task_id=task.task_id,
                    goal=task.goal,
                    version=parent.version,
                    text=need.question,
                    input_key=need.key,
                    **details,
                )
            )
    parent.pending_questions = questions
    focus = previous.question if previous else None
    parent.question = next(
        (
            q
            for q in questions
            if focus and q.task_id == focus.task_id and q.need_id == focus.need_id
        ),
        next(iter(questions), None),
    )


def combine_id_results(parent, results, *, previous=None, locale="ko", display_task_id=None):
    """Keep evidence identities scoped while exposing existing display fields."""
    from app.schemas.knowledge import KnowledgeReply
    from app.services.consultation_answer_service import independent_answer

    response = ChatResponse(answer="", products=[])
    parts, evidence, claims, knowledge_statuses, limits = [], [], [], [], []
    product_ids, style_ids = set(), set()
    prior_tasks = {t.task_id: t for t in previous.tasks} if previous else {}
    scoped_count = sum(
        any(
            getattr(r, field) is not None
            for field in ("option_search", "owned_look_options", "compound", "style_recipe")
        )
        for r in results.values()
    )
    for task in parent.tasks:
        result = results.get(task.task_id)
        if result is None:
            if task.status == "failed":
                parts.append(independent_answer(task, None, locale=locale))
            continue
        answer = (
            result.answer
            if task.product_assessment
            and task.product_assessment.outcome == "unsupported"
            and task.product_assessment.inspected == 0
            else independent_answer(
                task,
                result,
                prior_tasks.get(task.task_id),
                cards_visible=scoped_count <= 1,
                locale=locale,
            )
        )
        if previous is not None and task.reason == "preserved_completed_result":
            pending = [q.text for q in parent.pending_questions if q.task_id == task.task_id]
            if task.status == "waiting_user" and pending:
                # Stored questions own their text even when a legacy task has no input_needs.
                answer = ""
        if result.knowledge and not (
            previous is not None and task.reason == "preserved_completed_result"
        ):
            knowledge = result.knowledge
            mapping = {e.id: f"E{len(evidence) + i + 1}" for i, e in enumerate(knowledge.evidence)}
            if len(mapping) != len(knowledge.evidence) or any(
                citation not in mapping
                for claim in knowledge.claims
                for citation in claim.citations
            ):
                raise ValueError("Invalid knowledge citation mapping")
            # Substitute in one pass so renumbering cannot replace a newly written ID again.
            answer = re.sub(
                r"\[([^\[\]]+)\]", lambda m, refs=mapping: "[" + refs.get(m[1], m[1]) + "]", answer
            )
            evidence.extend(e.model_copy(update={"id": mapping[e.id]}) for e in knowledge.evidence)
            claims.extend(
                c.model_copy(update={"citations": [mapping[x] for x in c.citations]})
                for c in knowledge.claims
            )
            knowledge_statuses.append(knowledge.status)
            if knowledge.limitations:
                limits.append(knowledge.limitations)
        if answer and (task.reason != "preserved_completed_result" or answer not in parts):
            parts.append(answer)
        for product in result.products:
            if product.id not in product_ids:
                response.products.append(product)
                product_ids.add(product.id)
        for style in result.style_candidates or []:
            key = (style.kind, style.look_id)
            if key not in style_ids:
                if response.style_candidates is None:
                    response.style_candidates = []
                response.style_candidates.append(style)
                style_ids.add(key)
        if result.result_type == "clarification" and parent.question is None:
            parent.question = ParentQuestion(
                comparison_price_basis=result._comparison_price_basis,
                comparison_base_id=result._comparison_base_id,
                comparison_choices=result._comparison_choices,
                task_id=task.task_id,
                goal=task.goal,
                version=parent.version,
                text=result.answer,
                input_key="selection",
            )
        if result._owned_look_outcome and result.style_recipe:
            unknown = [
                item
                for item in result._owned_look_outcome.items
                if item.status == "ownership_unknown"
            ]
            if unknown and parent.question is None:
                item = unknown[0]
                parent.question = ParentQuestion(
                    task_id=task.task_id,
                    goal=task.goal,
                    version=parent.version,
                    text=f"{item.label} 제품을 가지고 있나요?",
                    input_key="ownership",
                    zone=item.zone,
                    need_id=item.need_id,
                    recipe_version=result.style_recipe.recipe_version,
                    ownership_scope="option",
                )
    response.answer = "\n\n".join(parts)
    response.result_type = "clarification" if parent.question else None
    if knowledge_statuses:
        response.knowledge = KnowledgeReply(
            status="answered"
            if all(s == "answered" for s in knowledge_statuses)
            and not any(
                t.goal == "knowledge" and t.status in {"failed", "partial", "waiting_user"}
                for t in parent.tasks
            )
            else "error"
            if all(s == "error" for s in knowledge_statuses)
            else "partial"
            if claims
            else "insufficient_evidence",
            claims=claims,
            evidence=evidence,
            limitations="\n".join(limits),
        )
    # Singular display contracts cannot truthfully represent multiple distinct query scopes.
    # Preserve them per task and require selection instead of collapsing scope/option evidence.
    scoped = [
        (task_id, r)
        for task_id, r in results.items()
        if any(
            getattr(r, field) is not None
            for field in ("option_search", "owned_look_options", "compound", "style_recipe")
        )
    ]
    changed_results = [
        (tid, r)
        for tid, r in results.items()
        if tid not in prior_tasks
        or next(t for t in parent.tasks if t.task_id == tid).reason != "preserved_completed_result"
    ]
    if previous is not None and scoped and len(changed_results) == 1:
        # One changed result already establishes focus; keep all old choices for later show.
        choices = list(dict.fromkeys([*(tid for tid, _ in scoped), changed_results[0][0]]))
        if len(choices) > 1:
            parent.result_selection = ResultSelection(version=parent.version, task_ids=choices)
        scoped = changed_results
        display_task_id = scoped[0][0]
    if len(scoped) == 1:
        if display_task_id:
            response.products = list(scoped[0][1].products)
        for field in (
            "option_search",
            "owned_look_options",
            "compound",
            "style_recipe",
            "style_status",
        ):
            setattr(response, field, getattr(scoped[0][1], field))
        if display_task_id and parent.result_selection:
            parent.result_selection.selected_task_id = display_task_id
    elif len(scoped) > 1:
        from app.services.consultation_result_service import result_label

        response.products = []
        response.result_type = "clarification"
        parent.result_selection = ResultSelection(
            version=parent.version,
            task_ids=[tid for tid, _ in scoped],
        )
        tasks = {t.task_id: t for t in parent.tasks}
        choices = "\n".join(
            f"{i}. {result_label(tasks[tid])}" for i, (tid, _) in enumerate(scoped, 1)
        )
        response.answer += "\n\n어느 요청의 결과부터 볼까요?\n" + choices
    elif display_task_id and parent.result_selection:
        parent.result_selection.selected_task_id = display_task_id
    if not display_task_id and len(scoped) <= 1:
        parent.result_selection = None
    if (
        display_task_id
        and parent.question
        and parent.question.task_id == display_task_id
        and parent.question.text not in response.answer
    ):
        response.answer += "\n\n" + parent.question.text
    return response


async def run_parent(
    req, kind, execute: Callable[[], Awaitable[ChatResponse]], *, catalog=None, trace=None
):
    previous = req._consultation_parent
    if previous and (kind == "skin") != any(t.goal == "skin" for t in previous.tasks):
        previous = None
    parent = previous.model_copy(deep=True) if previous else ConsultationParent()
    if previous:
        parent.version += 1
    parent.result_selection = None
    parent.pending_questions = []
    parent.execution_state = "active"
    parent.question = None
    parent.look = req.style_context
    events = trace if trace is not None else []
    response = None
    specialist_trace = []
    explanation_requested = kind == "owned_look" and wants_explanation(req.message)
    intent = req._parent_intent
    if req._parent_replan and any(
        t.goal == "knowledge" and t.task_id in req._parent_replan["withdrawn"] for t in parent.tasks
    ):
        explanation_requested = False
    knowledge_only = bool(
        intent and intent.action in {"retry", "resume"} and intent.targets == ["knowledge"]
    )
    if knowledge_only:
        response = ChatResponse(answer="", products=[], style_context=req.style_context)
        response._owned_look_context = req._owned_look_context

    class State(TypedDict):
        next_goal: str

    def plan(_state):
        if (
            _EXPLANATION_WITHDRAWAL.search(req.message)
            and not explanation_requested
            and not req._parent_replan
        ):
            for task in parent.tasks:
                if task.goal == "knowledge":
                    task.status = "superseded"
        if kind == "style":
            for task in parent.tasks:
                if task.goal == "owned_look":
                    task.status = "superseded"
        accept_task(
            parent,
            ParentTask(
                goal="knowledge" if knowledge_only else kind,
                objective=req.message,
                version=parent.version,
            ),
            parent.plan_id,
        )
        return {"next_goal": "knowledge" if knowledge_only else kind}

    async def work(state):
        nonlocal response
        task = next(t for t in parent.tasks if t.task_id == state["next_goal"])
        goal = task.goal
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
                if response._consultation_answer:
                    response._consultation_answer.explanation = consultation.answer
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
                validate_results(response._task_results)
                task.status = "partial"
                if response.result_type == "clarification":
                    task.status = "waiting_user"
                    parent.question = ParentQuestion(
                        task_id=task.task_id,
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
                    outcome = response._owned_look_outcome
                    if outcome is not None:
                        task.status = outcome.status
                        task.limitations = [
                            f"{item.label}: {item.status}"
                            for item in outcome.items
                            if item.status not in {"owned", "recommended"}
                        ]
                        unknown = [
                            item for item in outcome.items if item.status == "ownership_unknown"
                        ]
                        parent.question = None
                        if unknown:
                            item = unknown[0]
                            text = f"{item.label} 제품을 가지고 있나요?"
                            parent.question = ParentQuestion(
                                task_id=task.task_id,
                                goal=kind,
                                version=parent.version,
                                text=text,
                                input_key="ownership",
                                zone=item.zone,
                                need_id=item.need_id,
                                recipe_version=response.style_recipe.recipe_version,
                                ownership_scope="option",
                            )
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
        except (UpstreamError, ApiError, TimeoutError) as exc:
            task.status = "failed"
            task.reason = exc.code if isinstance(exc, ApiError) else "specialist_unavailable"
            task.limitations = [task.reason]
            if response is None:
                response = ChatResponse(
                    answer="요청한 자료를 조회하지 못했어요. 다시 시도해 주세요.", products=[]
                )
            else:
                notice = "추가 설명 자료를 조회하지 못했어요. 확인한 상품 결과는 유지했어요."
                if response._consultation_answer:
                    response._consultation_answer.notices.append(notice)
                else:
                    response.answer += "\n" + notice
        accept_task(parent, task, parent.plan_id)
        events.append(
            {
                "planId": str(parent.plan_id),
                "planVersion": parent.version,
                "task": task.model_dump(mode="json", by_alias=True),
                "inputs": inputs,
                "specialistTrace": list(specialist_trace) if goal == "owned_look" else [],
                "referenceInterpretation": response._owned_look_interpretation,
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

    async def coordinated_work(state):
        task = next(t for t in parent.tasks if t.task_id == state["next_goal"])
        request = ConsultationTaskRequest(
            task_id=task.task_id,
            capability=task.goal,
            inputs={"utterance": req.message, "planVersion": parent.version},
            depends_on=list(task.depends_on),
            requires_success=False,
        )
        result, _ = await execute_request(
            parent,
            task,
            request,
            lambda: work(state),
            classify=False,
            check_active=getattr(req._g7_execution, "check_active", None),
        )
        return result or {}

    graph.add_node("execute", coordinated_work)
    graph.add_node("assess", assess)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "assess")
    graph.add_conditional_edges("assess", lambda s: "execute" if s["next_goal"] else END)
    # Existing G8 request budget; each closed goal executes once. No new retry/LLM loop.
    try:
        budget = (
            max(0, req._parent_deadline - monotonic())
            if req._parent_deadline
            else get_settings().g8_deadline_seconds
        )
        async with asyncio.timeout(budget):
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
            notice = "추가 조회 시간이 초과되어 확인한 결과까지만 안내해 드려요."
            if response._consultation_answer:
                response._consultation_answer.notices.append(notice)
            else:
                response.answer += "\n" + notice
    parent = ConsultationParent.model_validate(parent.model_dump())
    response._consultation_parent = parent
    if req._parent_intent_audit:
        events.append({"parentIntent": req._parent_intent_audit})
    response._parent_trace = events
    return finalize_answer(response, parent.question)


async def try_owned_look(req, catalog, *, llm=None):
    if not get_settings().g8_enabled:
        return None
    previous = req._consultation_parent
    intent = req._parent_intent
    if req._parent_replan and "owned_look" in req._parent_replan["updated"]:
        req._owned_look_goal_followup = True
    if intent and intent.action == "delegate":
        return None
    if intent and intent.action in {"retry", "resume"} and intent.targets == ["knowledge"]:
        return await run_parent(req, "owned_look", lambda: None, catalog=catalog)
    if intent and intent.action in {"retry", "resume"} and "owned_look" in intent.targets:
        if not req._owned_look_context or not req.style_context:
            from app.services.consultation_intent_service import control_response

            return control_response(req, "이어갈 룩을 다시 선택해 주세요.", clarification=True)
        req._owned_look_goal_followup = True
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
    # A goal-only follow-up still belongs to the active owned-look consultation.
    product_only = bool(
        previous
        and previous.look
        and req.style_context
        and (previous.look.kind, previous.look.look_id)
        == (req.style_context.kind, req.style_context.look_id)
        and req._owned_look_context is not None
        and any(t.goal == "owned_look" and t.status != "superseded" for t in previous.tasks)
        and _EXPLANATION_WITHDRAWAL.search(req.message)
        and re.search(r"(?:상품|제품).*?(?:찾아|추천|보여)", req.message)
        and not owned_look_consultation_service._STATE_REQUEST.search(req.message)
    )
    from app.services.owned_look_interpreter import needs_reference

    reference = bool(
        previous
        and req._owned_look_context
        and req.style_context
        and (req.style_context.kind, req.style_context.look_id)
        == (req._owned_look_context.kind, req._owned_look_context.look_id)
        and needs_reference(req.message)
        and not owned_look_consultation_service._STATE_REQUEST.search(req.message)
    )
    if product_only or reference or req._question_answers:
        # Preserve the utterance for the parent and trace; the hint is server-only.
        req = req.model_copy()
        req._owned_look_goal_followup = True
        req._owned_look_reference = reference
        req._owned_look_llm = llm
    if not owned_look_consultation_service.may_consult_owned_look(req):
        return None

    async def owned():
        return await owned_look_consultation_service.execute_owned_look(req, catalog)

    return await run_parent(req, "owned_look", owned, catalog=catalog)
