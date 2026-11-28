"""Adapt live typed results, never reconstruct execution from logs or answer text."""

import hashlib
import json

from pydantic import BaseModel

from app.schemas.consultation_task import ConsultationTaskResult, TaskBinding, TaskInputNeed


def json_value(value):
    return json.loads(json.dumps(value, default=lambda v: v.model_dump(mode="json")))


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(json_value(value), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def adapt_specialist(task, result, inputs, sources, *, bound_inputs=None, attempt=1):
    from app.schemas.compound_consultation import TaskRequest, TaskResult
    from app.schemas.owned_look_consultation import OwnedLookResult, OwnedLookTask

    if isinstance(task, TaskRequest) and isinstance(result, TaskResult):
        family = "compound"
    elif isinstance(task, OwnedLookTask) and isinstance(result, OwnedLookResult):
        family = "owned_look"
    else:
        raise ValueError("Unsupported specialist contract")
    if (task.plan_id, task.plan_version, task.task_id) != (
        result.plan_id,
        result.plan_version,
        result.task_id,
    ):
        raise ValueError("Mismatched specialist result")
    values = inputs if bound_inputs is None else bound_inputs
    bindings = []
    for binding in task.input_bindings:
        if binding.source_task not in task.depends_on:
            raise ValueError("Binding without dependency")
        source = sources[binding.source_task]
        if (source.plan_id, source.plan_version, source.task_id) != (
            task.plan_id,
            task.plan_version,
            binding.source_task,
        ):
            raise ValueError("Stale input source")
        expected = getattr(source, binding.source_field)
        if fingerprint(values[binding.target_input]) != fingerprint(expected):
            raise ValueError("Bound input differs from source result")
        bindings.append(
            TaskBinding(
                source_task=binding.source_task,
                source_field=binding.source_field,
                target_input=binding.target_input,
                value_fingerprint=fingerprint(expected),
            )
        )
    return ConsultationTaskResult(
        plan_id=task.plan_id,
        plan_version=task.plan_version,
        task_id=task.task_id,
        family=family,
        capability=task.agent,
        status="completed" if result.status == "complete" else result.status,
        attempt=attempt,
        depends_on=list(task.depends_on),
        bindings=bindings,
        inputs=json_value(inputs),
        input_fingerprint=fingerprint(inputs),
        source_fingerprint=result.input_fingerprint,
        payload=result.model_copy(deep=True),
        limitations=list(result.limitations),
    )


def task_input_needs(task, payload):
    if task.status != "waiting_user" or payload is None:
        return []
    if task.input_needs and (
        task.reason == "preserved_completed_result" or payload._preserve_parent_context
    ):
        return [n.model_copy(deep=True) for n in task.input_needs]
    if payload._owned_look_outcome and payload.style_recipe:
        return [
            TaskInputNeed(
                key="ownership",
                question=f"{i.label} 제품을 가지고 있나요?",
                zone=i.zone,
                need_id=i.need_id,
                recipe_version=payload.style_recipe.recipe_version,
                ownership_scope="option",
            )
            for i in payload._owned_look_outcome.items
            if i.status == "ownership_unknown"
        ]
    if payload._comparison_choices:
        return [
            TaskInputNeed(
                question=payload.answer,
                comparison_base_id=payload._comparison_base_id,
                comparison_price_basis=payload._comparison_price_basis,
                comparison_choices=[c.model_dump() for c in payload._comparison_choices],
            )
        ]
    return (
        [
            TaskInputNeed(
                key="situation" if task.goal == "skin" else "selection", question=payload.answer
            )
        ]
        if payload.answer.strip()
        else []
    )


def adapt_independent(parent, task, payload, inputs):
    bindings = []
    reference = inputs.get("referenceContext", {}).get("styleRecipe")
    if reference is not None:
        from app.schemas.style_recipe import StyleRecipe

        if len(task.depends_on) != 1:
            raise ValueError("Ambiguous recipe source")
        bindings.append(
            TaskBinding(
                source_task=task.depends_on[0],
                source_field="style_recipe",
                target_input="referenceContext",
                value_fingerprint=fingerprint(StyleRecipe.model_validate(reference)),
            )
        )
    return ConsultationTaskResult(
        plan_id=parent.plan_id,
        plan_version=parent.version,
        task_id=task.task_id,
        family="independent",
        bindings=bindings,
        capability=task.goal,
        status="skipped" if task.status in {"pending", "cancelled", "superseded"} else task.status,
        attempt=task.attempts,
        depends_on=list(task.depends_on),
        inputs=json_value(inputs),
        input_fingerprint=fingerprint(inputs),
        payload=payload.model_copy(deep=True) if payload is not None else None,
        limitations=list(task.limitations),
        reason=task.reason,
        reused=task.reason == "preserved_completed_result",
        product_assessment=task.product_assessment,
        proposed_next_tasks=list(payload._proposed_next_tasks) if payload is not None else [],
        missing_inputs=task_input_needs(task, payload),
    )


def validate_results(records):
    """The parent checks identity, scope and bindings before consuming the result set."""
    if len({(r.plan_id, r.plan_version, r.family) for r in records}) > 1:
        raise ValueError("Mixed specialist execution scopes")
    indexed = {r.task_id: r for r in records}
    if len(indexed) != len(records):
        raise ValueError("Duplicate task result")
    for record in records:
        if fingerprint(record.inputs) != record.input_fingerprint:
            raise ValueError("Changed task inputs")
        if set(record.depends_on) - indexed.keys():
            raise ValueError("Missing dependency result")
        payload = record.payload
        assessment = record.product_assessment
        if assessment is not None and record.status != "skipped":
            if assessment.status != record.status:
                raise ValueError("Changed product assessment status")
            if assessment.requirement.kind and record.status == "completed" and payload is not None:
                verified = {
                    e.get("productId")
                    for e in assessment.evidence
                    if e.get("kind") == assessment.requirement.kind and e.get("verdict") == "match"
                }
                if {p.id for p in getattr(payload, "products", [])} - verified:
                    raise ValueError("Unverified product kind in completed result")
        if payload is not None and record.family != "independent":
            if not isinstance(payload, BaseModel) or (
                payload.plan_id,
                payload.plan_version,
                payload.task_id,
                payload.input_fingerprint,
            ) != (record.plan_id, record.plan_version, record.task_id, record.source_fingerprint):
                raise ValueError("Changed result identity")
            status = "completed" if payload.status == "complete" else payload.status
            if record.status != status:
                raise ValueError("Changed result status")
        for binding in record.bindings:
            if binding.source_task not in record.depends_on:
                raise ValueError("Binding without dependency")
            source = indexed[binding.source_task].payload
            if (
                source is None
                or fingerprint(getattr(source, binding.source_field)) != binding.value_fingerprint
            ):
                raise ValueError("Changed binding source")
    return records


def validate_continuation(parent, source_task, record, proposal, response):
    """Return a safe rejection code; a suggestion cannot grant new goals or permissions."""
    if (record.plan_id, record.plan_version, record.task_id) != (
        parent.plan_id,
        parent.version,
        source_task.task_id,
    ):
        return "stale_source"
    if source_task.goal != "owned_look" or proposal.capability != "knowledge":
        return "unsupported_binding"
    if not source_task.explanation_quote or proposal.objective != source_task.explanation_quote:
        return "outside_user_goal"
    if record.status not in {"completed", "partial", "waiting_user"} or response is None:
        return "unavailable_source"
    value = getattr(response, proposal.source_field, None)
    if value is None or fingerprint(value) != proposal.source_fingerprint:
        return "changed_source"
    return None
