"""Assess structured parent outcomes; display selection never changes execution success."""

from app.schemas.consultation_parent import ConsultationSummary, ResultChoice


def result_label(task):
    # The objective's first line is the user's grounded quote, not an internal trace.
    return (
        task.objective.split("\n", 1)[0].strip()
        or {
            "skin": "피부 상담",
            "owned_look": "룩에 필요한 상품",
            "knowledge": "설명",
            "style": "룩",
            "product": "상품",
        }[task.goal]
    )


def selection_task_ids(parent):
    selection = parent.result_selection
    if selection is None or selection.version != parent.version:
        return []
    tasks = {t.task_id: t for t in parent.tasks}
    return [
        tid
        for tid in selection.task_ids
        if tid in tasks
        and tasks[tid].status in {"completed", "partial", "waiting_user"}
        and tasks[tid].display_result is not None
    ]


def finalize_result(response):
    parent = response._consultation_parent
    if parent is None:
        return response
    if parent.result_selection:
        selection = parent.result_selection
        selection.task_ids = selection_task_ids(parent)
        if selection.selected_task_id not in selection.task_ids:
            selection.selected_task_id = None
        if not selection.task_ids:
            parent.result_selection = None
    active = [t for t in parent.tasks if t.status not in {"cancelled", "superseded"}]
    statuses = {t.status for t in active}
    needs_input = (
        parent.question is not None
        or bool(parent.pending_questions)
        or "waiting_user" in statuses
        or (response.result_type == "clarification" and parent.result_selection is None)
    )
    if parent.execution_state == "cancelled" or (parent.tasks and not active):
        status = "cancelled"
    elif not active:
        status = "waiting_user" if needs_input else "pending"
    elif statuses == {"completed"} and not needs_input:
        status = "completed"
    elif statuses == {"failed"} and not needs_input:
        status = "failed"
    elif statuses <= {"pending", "waiting_user", "failed"}:
        status = "waiting_user" if needs_input else "pending"
    else:
        status = "partial"
    selection = parent.result_selection
    tasks = {t.task_id: t for t in active}
    choices = (
        [
            ResultChoice(task_id=tid, label=result_label(tasks[tid]))
            for tid in selection.task_ids
            if tid in tasks and tasks[tid].display_result is not None
        ]
        if selection
        else []
    )
    selected = (
        selection.selected_task_id
        if selection and any(c.task_id == selection.selected_task_id for c in choices)
        else None
    )
    response.consultation = ConsultationSummary(
        status=status,
        has_pending_input=needs_input,
        display_selection_required=len(choices) > 1 and selected is None,
        display_choices=choices,
        selected_task_id=selected,
    )
    return response
