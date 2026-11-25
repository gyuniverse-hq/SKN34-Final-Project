"""Translate persisted, validated conversation state into the existing chat contract."""

import time
from collections.abc import Sequence

from app.core.errors import ApiError, UpstreamError
from app.schemas.chat import (
    BeautyContext,
    BeautyFilters,
    ChatRequest,
    ChatResponse,
    RecentChatMessage,
)
from app.schemas.conversation import (
    StoredConversationContext,
    StoredProductContext,
    StoredStyleContext,
    UpdateConversationStateRequest,
)
from app.schemas.style_recipe import StyleCandidateRef, StyleContext
from app.schemas.supervisor import ScreenContext
from app.services.style_recipe_service import execute_style

_DISPLAY_FIELDS = {
    "appliedMemories",
    "products",
    "styleCandidates",
    "styleRecipe",
    "optionSearch",
    "ingredientResults",
    "evidence",
    "knowledge",
    "ingredientComparison",
    "fragranceSearchSummary",
    "resultType",
    "styleStatus",
    "styleContext",
    "styleConditions",
}
_FORBIDDEN_KEYS = {
    "authorization",
    "sessiontoken",
    "sessionid",
    "resultsetid",
    "faceimage",
    "facevideo",
    "accesstoken",
    "refreshtoken",
    "chatcontext",
    "token",
    "session",
    "apikey",
    "password",
    "secret",
    "prompt",
    "rawtoolresult",
    "image",
    "imagedata",
    "imagebase64",
    "video",
    "videoframe",
}


def _sanitize(value):
    if isinstance(value, dict):
        return {
            key: _sanitize(item)
            for key, item in value.items()
            if isinstance(key, str) and key.replace("_", "").lower() not in _FORBIDDEN_KEYS
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def read_context(raw: dict) -> StoredConversationContext:
    context = StoredConversationContext.model_validate(raw)
    if context.product:
        context.product.filters = BeautyFilters.model_validate(context.product.filters).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
    return context


def prepare_request(
    request: ChatRequest,
    raw: dict,
    messages: Sequence,
    memory_versions: dict[str, int] | None = None,
    removed_sources: set[str] | None = None,
    history_cutoff=None,
) -> ChatRequest:
    context = read_context(raw)
    recent = []
    budget = 8000
    # Take complete user/assistant pairs, newest first, then restore chronological order.
    pairs = [messages[i : i + 2] for i in range(0, len(messages) - 1, 2)]
    for pair in reversed(pairs):
        if len(pair) != 2 or [item.role for item in pair] != ["user", "assistant"]:
            continue
        if removed_sources and any(str(item.id) in removed_sources for item in pair):
            continue
        if history_cutoff and any(item.created_at <= history_cutoff for item in pair):
            continue
        if memory_versions is not None and any(
            not isinstance(ref, dict)
            or set(ref) != {"memoryId", "version"}
            or not isinstance(ref.get("memoryId"), str)
            or type(ref.get("version")) is not int
            or memory_versions.get(ref.get("memoryId")) != ref.get("version")
            for item in pair
            for ref in (getattr(item, "memory_refs", None) or [])
        ):
            continue
        texts = [item.text[: 1000 if item.role == "user" else 2000] for item in pair]
        if not all(texts) or sum(map(len, texts)) > budget:
            continue
        budget -= sum(map(len, texts))
        recent[0:0] = [
            RecentChatMessage(id=str(item.id), role=item.role, text=text)
            for item, text in zip(pair, texts, strict=True)
        ]
    style = None
    if context.style:
        style = StyleContext.model_validate(
            context.style.model_dump(
                by_alias=True, exclude={"conditions", "historical_candidate_refs"}
            )
        )
    beauty = None
    if context.product:
        beauty = BeautyContext(
            issued_at=int(time.time()),
            filters=BeautyFilters.model_validate(context.product.filters),
            selected_product_id=context.product.selected_product_id,
            shade_selections=(
                {context.product.selected_product_id: context.product.selected_shade_id}
                if context.product.selected_product_id and context.product.selected_shade_id
                else {}
            ),
        )
    # Client history, selected state and candidate hints are never used as the durable source.
    result = request.model_copy(
        deep=True,
        update={
            "recent_messages": recent,
            "chat_context": beauty,
            "style_context": style,
            "screen_context": (
                ScreenContext(
                    screen_id="product-detail",
                    product_id=beauty.selected_product_id,
                    shade_id=beauty.shade_selections.get(beauty.selected_product_id),
                )
                if beauty and beauty.selected_product_id
                else None
            ),
            "clarification_id": None,
            "excluded_style": (
                StyleCandidateRef(kind=style.kind, look_id=style.look_id)
                if request.excluded_style
                and style
                and (request.excluded_style.kind, request.excluded_style.look_id)
                == (style.kind, style.look_id)
                else None
            ),
            "previous_style_candidates": context.style_candidates
            if request.previous_style_candidates
            else [],
            "previous_style_selection": (
                StyleCandidateRef(kind=style.kind, look_id=style.look_id)
                if request.previous_style_selection and style
                else None
            ),
            "style_conditions": (
                context.style.conditions if context.style else context.style_conditions or None
            ),
            "style_compare": bool(request.style_compare and context.style_candidates),
        },
    )
    result._server_history = True
    return result


async def revalidate_request(chat, request: ChatRequest) -> None:
    beauty = request.chat_context
    selected = beauty.selected_product_id if beauty else None
    style = request.style_context
    if not selected and style is None:
        return
    catalog = getattr(chat, "_catalog", None)
    if catalog is None:
        raise ApiError(503, "Catalog is unavailable", "catalog_unavailable")
    try:
        if selected:
            product = await catalog.get_product(selected)
            if product is None or product.id != selected:
                raise ApiError(
                    409, "Selected product needs revalidation", "conversation_needs_revalidation"
                )
            shade = beauty.shade_selections.get(selected)
            if shade and not any(item.id == shade for item in product.shades):
                raise ApiError(
                    409, "Selected shade needs revalidation", "conversation_needs_revalidation"
                )
        if style:
            look = await catalog.get_style_look(style.kind, style.look_id)
            if look is None or look.id != style.look_id:
                raise ApiError(
                    409, "Selected look needs revalidation", "conversation_needs_revalidation"
                )
    except UpstreamError as exc:
        raise ApiError(503, "Catalog is unavailable", "catalog_unavailable") from exc


def updated_context(raw: dict, response: ChatResponse) -> dict:
    context = read_context(raw)
    if response.chat_context is not None:
        beauty = response.chat_context
        selected = beauty.selected_product_id
        context.product = StoredProductContext(
            selected_product_id=selected,
            selected_shade_id=beauty.shade_selections.get(selected) if selected else None,
            filters=beauty.filters.model_dump(mode="json", by_alias=True, exclude_none=True),
            historical_candidate_refs=list(beauty.candidate_ids),
        )
    if response.style_context is not None:
        style = response.style_context.model_dump(mode="json", by_alias=True)
        if response.style_conditions is not None:
            style["conditions"] = [
                item.model_dump(mode="json", by_alias=True) for item in response.style_conditions
            ]
        context.style = StoredStyleContext.model_validate(style)
    if response.style_candidates is not None:
        context.style_candidates = [
            StyleCandidateRef(kind=item.kind, look_id=item.look_id)
            for item in response.style_candidates[:6]
        ]
    if response.style_conditions is not None:
        context.style_conditions = list(response.style_conditions)
    return context.model_dump(mode="json", by_alias=True, exclude_none=True)


async def apply_state_update(
    raw: dict, subject: dict, body: UpdateConversationStateRequest, chat
) -> dict:
    context = read_context(raw)
    operation, payload = body.operation, body.payload
    if operation == "clear_selection":
        if context.product:
            context.product.selected_product_id = None
            context.product.selected_shade_id = None
        context.style = None
        return context.model_dump(mode="json", by_alias=True, exclude_none=True)

    catalog = getattr(chat, "_catalog", None)
    if catalog is None:
        raise ApiError(503, "Catalog is unavailable", "catalog_unavailable")
    try:
        if operation in {"select_product", "select_shade"}:
            product_id = payload["productId"]
            product = await catalog.get_product(product_id)
            if product is None or product.id != product_id:
                raise ApiError(404, "Product not found", "product_not_found")
            shade_id = payload.get("shadeId")
            if shade_id is not None and not any(shade.id == shade_id for shade in product.shades):
                raise ApiError(404, "Shade not found", "shade_not_found")
            product_context = context.product or StoredProductContext()
            if product_context.selected_product_id != product_id:
                product_context.historical_candidate_refs = []
            product_context.selected_product_id = product_id
            product_context.selected_shade_id = shade_id
            context.product = product_context
        else:
            kind, look_id = payload["kind"], payload["lookId"]
            if operation == "select_look":
                look = await catalog.get_style_look(kind, look_id)
                if look is None or look.id != look_id:
                    raise ApiError(404, "Look not found", "style_look_not_found")
                context.style = StoredStyleContext(kind=kind, look_id=look_id)
            else:
                selected = context.style
                if selected and (selected.kind != kind or selected.look_id != look_id):
                    raise ApiError(409, "Selected look changed", "conversation_conflict")
                if (
                    not selected
                    and subject.get("type") == "look"
                    and (subject.get("kind") != kind or subject.get("lookId") != look_id)
                ):
                    raise ApiError(409, "Selected look changed", "conversation_conflict")
                request = ChatRequest(
                    message="단계 안내",
                    locale="ko",
                    request_type="style_consultation",
                    style_context=StyleContext(kind=kind, look_id=look_id),
                )
                response, _ = await execute_style(request, catalog)
                if response.style_status == "error":
                    raise ApiError(503, "Look is unavailable", "catalog_unavailable")
                if response.style_status == "not_found":
                    raise ApiError(404, "Look not found", "style_look_not_found")
                recipe = response.style_recipe
                if recipe is None or not recipe.steps:
                    raise ApiError(409, "Recipe steps are unavailable", "recipe_unavailable")
                if recipe.recipe_version != payload["recipeVersion"]:
                    raise ApiError(409, "Recipe version changed", "recipe_changed")
                if payload["currentStep"] >= len(recipe.steps):
                    raise ApiError(400, "Invalid recipe step", "invalid_request")
                context.style = StoredStyleContext(
                    kind=kind,
                    look_id=look_id,
                    recipe_id=recipe.recipe_id,
                    recipe_version=recipe.recipe_version,
                    current_step=payload["currentStep"],
                    conditions=selected.conditions if selected else [],
                    historical_candidate_refs=selected.historical_candidate_refs
                    if selected
                    else [],
                )
    except UpstreamError as exc:
        raise ApiError(503, "Catalog is unavailable", "catalog_unavailable") from exc
    return context.model_dump(mode="json", by_alias=True, exclude_none=True)


def display_payload(response: ChatResponse) -> dict:
    payload = response.model_dump(mode="json", by_alias=True, exclude_none=True)
    result = _sanitize({key: value for key, value in payload.items() if key in _DISPLAY_FIELDS})
    for item in result.get("ingredientResults", []):
        item.setdefault("shadeId", None)
    if response.chat_context and any(item.shade_id for item in response.ingredient_results or []):
        result["resultContext"] = {
            "issuedAt": response.chat_context.issued_at,
            "shadeSelections": dict(response.chat_context.shade_selections),
        }
    return result


def restore_response(answer: str, payload: dict) -> ChatResponse:
    # A missing ephemeral Redis capability is intentional and must never be replayed.
    fields = dict(payload)
    result_context = fields.pop("resultContext", None)
    if result_context is not None:
        fields["chatContext"] = {
            "issuedAt": result_context["issuedAt"],
            "filters": {},
            "shadeSelections": result_context["shadeSelections"],
        }
        fields["sessionStatus"] = "unavailable"
    return ChatResponse.model_validate({"answer": answer, "products": [], **fields})
