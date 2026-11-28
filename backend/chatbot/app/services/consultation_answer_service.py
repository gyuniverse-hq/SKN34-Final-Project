"""Render verified N02 facts after parent assessment, without an extra model call."""

from app.schemas.consultation_answer import ConsultationAnswer, IndependentAnswer

PRODUCT_LABELS = {
    "toner": "토너",
    "cream": "크림",
    "lotion": "로션",
    "serum": "세럼·에센스",
    "cleanser": "클렌저",
    "sunscreen": "자외선 차단제",
    "mask": "마스크·팩",
    "cleansing_cream": "클렌징크림",
    "tone_up_cream": "톤업크림",
    "eye_cream": "아이크림",
    "lip": "립 제품",
    "cheek": "블러셔",
    "eye": "아이 메이크업 제품",
    "base": "베이스 제품",
    "skincare": "스킨케어 제품",
    "suncare": "자외선 차단 제품",
}


def independent_answer(task, result, previous=None, *, cards_visible=True, locale="ko"):
    """Use assessed facts for product copy, preserving other specialists' sourced text."""
    if result is None:
        labels = {"product": "상품", "knowledge": "설명", "style": "룩"}
        return (
            f"{labels.get(task.goal, '요청하신 내용')}은 이번에 확인하지 못했어요."
            if locale == "ko"
            else "This part could not be checked."
        )
    if (
        previous is not None
        and task.reason == "preserved_completed_result"
        and task.goal != "product"
    ):
        labels = {
            "skin": "피부 상담 내용과 상품 후보는",
            "knowledge": "앞서 안내한 설명은",
            "owned_look": "룩 상담 내용은",
            "style": "앞서 찾은 룩은",
        }
        suffix = " 확인하지 못한 부분도 남아 있어요." if task.status == "partial" else ""
        if task.status == "waiting_user":
            if not task.input_needs:
                return result.answer
            suffix = "\n\n" + "\n".join(n.question for n in task.input_needs)
        return labels[task.goal] + " 그대로 유지했어요." + suffix
    assessment = task.product_assessment
    if task.goal != "product" or assessment is None or result.result_type == "clarification":
        return result.answer
    if locale != "ko":
        return result.answer
    if task.product_operation in {"compare", "detail"}:
        if task.reason == "preserved_completed_result":
            return (
                "앞서 비교한 내용은 그대로 유지했어요."
                if task.product_operation == "compare"
                else "앞서 확인한 상품 정보는 그대로 유지했어요."
            )
        return result.answer
    filters = (task.product_context or {}).get("filters", {})
    old = (previous.product_context or {}).get("filters", {}) if previous else {}
    kind = assessment.requirement.kind
    old_kind = (
        previous.product_requirement.kind if previous and previous.product_requirement else None
    )
    facts = IndependentAnswer(
        label=PRODUCT_LABELS.get(kind or filters.get("category"), "상품"),
        card_ids=[p.id for p in result.products],
        preserved=task.reason == "preserved_completed_result",
        kind_cleared=old_kind is not None and kind is None,
        kind_changed=old_kind is not None and kind is not None and old_kind != kind,
        budget=filters.get("maxPriceKRW"),
        budget_changed=bool(previous and old.get("maxPriceKRW") != filters.get("maxPriceKRW")),
        moisturizing=bool(filters.get("moisturizing")),
        preference_changed=bool(
            previous and old.get("moisturizing") != filters.get("moisturizing")
        ),
        status=assessment.status,
        outcome=assessment.outcome,
        cards_visible=cards_visible,
    )
    if len(facts.card_ids) != len(set(facts.card_ids)):
        raise ValueError("Duplicate independent answer cards")
    if facts.preserved:
        return f"{facts.label} 추천은 그대로 유지했어요."
    lines = []
    if facts.kind_cleared:
        lines.append("상품 종류 제한은 풀었어요.")
    elif facts.kind_changed:
        lines.append(f"상품 종류를 {facts.label}으로 바꿨어요.")
    if facts.budget is not None:
        verb = (
            "맞췄어요" if facts.budget_changed else "유지했어요" if previous and old else "찾았어요"
        )
        lines.append(f"{facts.label}은 {facts.budget:,}원 이하로 {verb}.")
    elif facts.budget_changed:
        lines.append("예산 제한은 해제했어요.")
    if facts.moisturizing and facts.preference_changed:
        lines.append(f"{facts.label}만 보습 선호를 반영해 다시 골랐어요.")
    elif facts.preference_changed:
        lines.append("보습 선호는 해제했어요.")
    if facts.status == "partial":
        # Keep the specialist's precise unsupported/unknown-condition explanation.
        lines.append(result.answer)
    elif facts.outcome == "no_match":
        lines.append(f"현재 조건에 맞는 {facts.label} 후보는 찾지 못했어요.")
    elif facts.card_ids:
        lines.append(f"조건에 맞는 {facts.label} 후보 {len(facts.card_ids)}개를 찾았어요.")
        if facts.cards_visible:
            lines.append("아래 상품 카드에서 확인해 보세요.")
    else:
        return result.answer  # Existing detail/comparison prose is already sourced.
    if facts.moisturizing and facts.card_ids:
        lines.append("보습 선호는 상품 설명을 참고해 반영했으며, 실제 효과를 확인한 것은 아니에요.")
    if facts.budget is not None and facts.card_ids:
        lines.append(
            "가격은 앱 등록 가격 기준이며, 구매할 옵션의 가격은 상세 화면에서 확인해 주세요."
        )
    return "\n".join(lines)


def validate_answer_facts(facts, response, question=None):
    if set(facts.card_ids) != {p.id for p in response.products}:
        raise ValueError("Answer/card mismatch")
    known = {c.need_id: c for c in facts.coverage}
    if len(known) != len(facts.coverage):
        raise ValueError("Duplicate answer target")
    if {i.need_id for i in facts.outcome.items} != set(known):
        raise ValueError("Incomplete answer targets")
    for item in facts.outcome.items:
        coverage = known.get(item.need_id)
        if coverage is None or coverage.label != item.label:
            raise ValueError("Unknown answer target")
        if item.status == "recommended" and coverage.product_id not in facts.card_ids:
            raise ValueError("Recommendation without a card")
        if item.status == "owned" and coverage.status != "fulfilled":
            raise ValueError("Unverified ownership")
        if item.status == "recommended":
            if coverage.status != "confirmed_missing":
                raise ValueError("Unverified recommendation")
            if coverage.option_id and not any(
                (o.product_id, o.option_id, o.shade_id)
                == (coverage.product_id, coverage.option_id, coverage.shade_id)
                for o in facts.options
            ):
                raise ValueError("Recommendation option mismatch")
    expected = {(o.product_id, o.option_id, o.shade_id) for o in facts.options}
    actual = (
        {(o.product_id, o.option_id, o.shade_id) for o in response.owned_look_options.selections}
        if response.owned_look_options
        else set()
    )
    if actual != expected:
        raise ValueError("Answer/option mismatch")
    if (
        question
        and question.input_key == "ownership"
        and (
            question.recipe_version != facts.current.recipe_version
            or not any(
                item.need_id == question.need_id and item.status == "ownership_unknown"
                for item in facts.outcome.items
            )
        )
    ):
        raise ValueError("Answer/question mismatch")


def render_answer(facts: ConsultationAnswer, question=None):
    previous, current = facts.previous, facts.current
    followup = previous is not None
    lines = []
    known = {c.need_id: c for c in facts.coverage}
    exempted = set(current.exceptions) - (set(previous.exceptions) if previous else set())
    if exempted:
        labels = [c.label for c in facts.coverage if c.need_id in exempted]
        lines.append(", ".join(labels) + " 제품은 ‘없음’ 조건에서 뺐어요.")
    budget_changed = (
        previous is not None and previous.filters.max_price_krw != current.filters.max_price_krw
    )
    if budget_changed and not current.filters.unsupported:
        budget = current.filters.max_price_krw
        lines.append(
            f"예산을 {budget:,}원 이하로 바꿨어요."
            if budget is not None
            else "예산 제한을 해제했어요."
        )
        if current.exceptions:
            lines.append("미보유 조건에서 뺀 제품은 그대로 유지했어요.")
    declarations_changed = previous is not None and any(
        [
            previous.declarations != current.declarations,
            previous.item_declarations != current.item_declarations,
            previous.product_declarations != current.product_declarations,
            previous.exceptions != current.exceptions,
        ]
    )
    if declarations_changed and not exempted:
        lines.append("말씀하신 보유 조건을 반영했어요.")
    if (
        previous
        and previous.filters != current.filters
        and not budget_changed
        and not current.filters.unsupported
    ):
        lines.append("요청하신 상품 조건을 반영했어요.")
    recommendations = [i for i in facts.outcome.items if i.status == "recommended"]
    owned = [i for i in facts.outcome.items if i.status == "owned"]
    if recommendations:
        names = ", ".join(i.label for i in recommendations)
        lines.append(f"추가로 구매할 제품으로 {names} 제품을 추천해요.")
        lines.append(
            "이 룩에 연결된 상품 중 없다고 알려주신 제품이에요."
            if not followup
            else "아래 상품 카드에서 확인해 보세요."
        )
    elif owned and len(owned) == len(facts.outcome.items):
        lines.append("이 룩에 연결된 상품·호수는 모두 가지고 계시네요. 추가로 살 제품은 없어요.")
    elif not any(i.status == "ownership_unknown" for i in facts.outcome.items):
        lines.append("지금 조건으로는 추가 후보를 확정하지 못했어요.")
    if not followup and owned and recommendations:
        lines.append(
            "가지고 계신 " + ", ".join(i.label for i in owned) + " 제품은 추가 추천에서 뺐어요."
        )
    notices = {}
    for item in facts.outcome.items:
        if item.status == "excluded":
            lines.append(f"{item.label} 제품은 요청하신 조건에 맞지 않아 추천에서 뺐어요.")
        elif item.status == "lookup_failed":
            lines.append(
                f"{item.label} 제품은 정보를 불러오지 못했어요."
                + (" 확인된 다른 추천은 유지했어요." if recommendations else "")
            )
        elif item.status == "evidence_missing":
            gap = known[item.need_id]
            reason = (
                "보유품이 이 룩의 대체품으로 적합한지는 아직 확인하지 못했어요."
                if gap.alternative_product_ids
                else "정확한 옵션이나 요청하신 조건을 확인할 정보가 부족해요."
            )
            notices.setdefault(reason, []).append(item.label)
    for reason, labels in notices.items():
        lines.append(", ".join(labels) + ": " + reason)
    if not followup:
        lines.extend(facts.alternatives)
    if facts.unverified_roles and not followup:
        lines.append(
            "같은 부위의 제품을 모두 함께 써야 하는지, "
            "서로 대체할 수 있는지는 아직 확인되지 않았어요."
        )
    if facts.guidance:
        lines.append(
            "일반적인 메이크업 순서로 안내할게요. 영상의 실제 사용 순서는 확인되지 않았어요."
            if facts.general_guidance
            else "룩에 등록된 사용 순서예요."
        )
        lines.extend(facts.guidance)
    if facts.incomplete_search:
        lines.append("일부 옵션은 아직 확인하지 못했어요.")
    if current.filters.price_basis == "current_offer":
        lines.append("실시간 현재가는 확인하지 못했어요. 구매 화면에서 가격을 확인해 주세요.")
    elif recommendations and current.filters.max_price_krw is not None:
        lines.append("가격은 달라질 수 있으니 구매 전에 상품 화면에서 확인해 주세요.")
    lines.extend(facts.notices)
    if facts.explanation:
        lines.append(facts.explanation)
    unknown = next((i for i in facts.outcome.items if i.status == "ownership_unknown"), None)
    # Keep the parent's exact option question. Budget-only turns need not repeat it.
    if unknown and not (
        budget_changed
        and not declarations_changed
        and facts.previous_question_id == unknown.need_id
    ):
        lines.append(
            question.text
            if question and question.input_key == "ownership"
            else f"{unknown.label} 제품을 가지고 있나요?"
        )
    return (
        "\n\n".join(dict.fromkeys(line for line in lines if line))
        or "어떤 제품이 필요한지 조금 더 확인할게요."
    )


def finalize_answer(response, question=None):
    facts = response._consultation_answer
    if facts is None:
        return response
    validate_answer_facts(facts, response, question)
    response.answer = render_answer(facts, question)
    return response
