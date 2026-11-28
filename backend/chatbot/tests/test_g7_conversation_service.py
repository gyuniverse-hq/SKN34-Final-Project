from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.core.errors import ApiError
from app.schemas.catalog import CatalogLook
from app.schemas.chat import BeautyContext, BeautyFilters, ChatRequest, ChatResponse, ChatSessionRef
from app.schemas.conversation import UpdateConversationStateRequest
from app.schemas.style_recipe import StyleContext
from app.services.chat_service import build_messages
from app.services.conversation_context import (
    apply_state_update,
    display_payload,
    prepare_request,
    restore_response,
    revalidate_request,
    updated_context,
)
from app.services.conversation_service import ConversationService, _fingerprint, require_persistence
from app.services.style_recipe_service import execute_style


def test_server_history_replaces_client_state_and_works_with_g1_off(monkeypatch):
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", False)
    request = ChatRequest.model_validate(
        {
            "message": "what next?",
            "locale": "en",
            "styleContext": {"kind": "video", "lookId": "untrusted"},
        }
    )
    messages = [
        SimpleNamespace(id=uuid4(), role="user", text="my first question"),
        SimpleNamespace(id=uuid4(), role="assistant", text="first answer"),
    ]
    prepared = prepare_request(request, {}, messages)
    assert prepared.style_context is None
    assert [item.text for item in prepared.recent_messages] == ["my first question", "first answer"]
    prompt = build_messages(prepared, [])
    assert [item["content"] for item in prompt[1:]] == [
        "my first question",
        "first answer",
        "what next?",
    ]
    assert "serverHistory" not in prepared.model_dump(mode="json", by_alias=True)


def test_client_cannot_enable_the_trusted_server_history_flag():
    request = ChatRequest.model_validate(
        {"message": "hi", "_server_history": True, "serverHistory": True}
    )
    assert request._server_history is False


def test_existing_chat_fingerprint_is_unchanged_without_clarification():
    request = ChatRequest(
        message="hi", conversation_id=uuid4(), request_id=uuid4(), expected_conversation_version=0
    )
    fields = {
        "conversationId": str(request.conversation_id),
        "message": "hi",
        "locale": "en",
        "requestType": "chat",
        "expectedConversationVersion": 0,
        "skin": None,
        "styleSearch": False,
        "generalMakeup": False,
    }
    assert ConversationService._request_fingerprint("owner", request) == _fingerprint(
        "owner", "chat", fields
    )


def test_token_free_reply_can_be_restored():
    response = ChatResponse(answer="hello", products=[])
    stored = display_payload(response)
    assert stored == {"products": []}
    assert restore_response(response.answer, stored).answer == "hello"


def test_redis_capability_is_not_copied_into_persistent_state():
    token = "x" * 40
    session_id = uuid4()
    context = BeautyContext(
        issued_at=1,
        filters=BeautyFilters(),
        session=ChatSessionRef(
            session_id=session_id,
            session_token=token,
            result_set_id=uuid4(),
            state_version=1,
            expires_at=9999999999,
        ),
    )
    response = ChatResponse(answer="hello", products=[], chat_context=context)
    assert token not in str(display_payload(response))
    assert token not in str(updated_context({}, response))
    assert str(session_id) not in str(updated_context({}, response))


def test_shade_ingredient_result_can_be_replayed_without_redis_capability():
    response = ChatResponse.model_validate(
        {
            "answer": "ingredient details",
            "products": [{"id": "lip-1", "brand": "B", "name": "Lip", "category": "lip"}],
            "chatContext": {"issuedAt": 1, "filters": {}, "shadeSelections": {"lip-1": "s1"}},
            "ingredientResults": [
                {
                    "productId": "lip-1",
                    "shadeId": "s1",
                    "status": "unknown",
                    "verdict": "UNKNOWN",
                    "mappingStatus": "unmapped",
                    "ingredientCoverage": "unknown",
                    "reviewStatus": "unreviewed",
                    "normalizationStatus": "unverified",
                    "ingredients": [],
                    "reason": "not verified",
                }
            ],
        }
    )
    stored = display_payload(response)
    replay = restore_response(response.answer, stored)
    assert replay.ingredient_results[0].shade_id == "s1"
    assert replay.chat_context.session is None
    assert replay.session_status == "unavailable"


def test_shared_environments_are_closed_even_if_flag_is_enabled(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "g7_persistence_enabled", True)
    monkeypatch.setattr(settings, "chat_database_url", "postgresql+asyncpg://unused")
    for env in ("production", "staging", "dev"):
        monkeypatch.setattr(settings, "env", env)
        with pytest.raises(ApiError) as exc:
            require_persistence()
        assert (exc.value.status, exc.value.code) == (503, "persistence_unavailable")


def test_disabled_feature_is_distinct_from_missing_database(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(settings, "chat_database_url", "")
    monkeypatch.setattr(settings, "g7_persistence_enabled", False)
    with pytest.raises(ApiError) as disabled:
        require_persistence()
    assert disabled.value.code == "persistence_disabled"
    monkeypatch.setattr(settings, "g7_persistence_enabled", True)
    with pytest.raises(ApiError) as unavailable:
        require_persistence()
    assert unavailable.value.code == "persistence_unavailable"


@pytest.mark.anyio
async def test_stale_server_selection_is_rejected_before_chat_execution():
    class MissingCatalog:
        async def get_product(self, product_id):
            return None

    request = prepare_request(
        ChatRequest(message="that product"),
        {"schemaVersion": 1, "product": {"selectedProductId": "gone", "filters": {}}},
        [],
    )
    with pytest.raises(ApiError) as exc:
        await revalidate_request(SimpleNamespace(_catalog=MissingCatalog()), request)
    assert (exc.value.status, exc.value.code) == (409, "conversation_needs_revalidation")


@pytest.mark.anyio
async def test_recipe_step_requires_current_catalog_version_and_valid_range():
    look = CatalogLook.model_validate(
        {
            "id": "look-1",
            "title": "Look",
            "tags": [],
            "items": [],
            "makeup": {"brow": {"hex": "#775544"}, "lip": {"hex": "#aa5544"}},
            "stepOrder": ["brow", "lip"],
        }
    )

    class Catalog:
        async def get_style_look(self, kind, look_id):
            return look if kind == "catalog" and look_id == look.id else None

    catalog = Catalog()
    request = ChatRequest(
        message="단계 안내",
        locale="ko",
        request_type="style_consultation",
        style_context=StyleContext(kind="catalog", look_id=look.id),
    )
    response, _ = await execute_style(request, catalog)
    assert response.style_recipe and len(response.style_recipe.steps) == 2
    version = response.style_recipe.recipe_version
    body = UpdateConversationStateRequest.model_validate(
        {
            "requestId": str(uuid4()),
            "expectedConversationVersion": 0,
            "operation": "set_recipe_step",
            "payload": {
                "kind": "catalog",
                "lookId": "look-1",
                "recipeVersion": version,
                "currentStep": 1,
            },
        }
    )
    subject = {"type": "look", "kind": "catalog", "lookId": "look-1"}
    raw = {"style": {"kind": "catalog", "lookId": "look-1", "currentStep": 0}}
    result = await apply_state_update(raw, subject, body, SimpleNamespace(_catalog=catalog))
    assert result["style"]["currentStep"] == 1 and result["style"]["recipeVersion"] == version
    stale = body.model_copy(update={"payload": {**body.payload, "recipeVersion": "old"}})
    with pytest.raises(ApiError) as exc:
        await apply_state_update(raw, subject, stale, SimpleNamespace(_catalog=catalog))
    assert (exc.value.status, exc.value.code) == (409, "recipe_changed")
    invalid = body.model_copy(update={"payload": {**body.payload, "currentStep": 2}})
    with pytest.raises(ApiError) as exc:
        await apply_state_update(raw, subject, invalid, SimpleNamespace(_catalog=catalog))
    assert (exc.value.status, exc.value.code) == (400, "invalid_request")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_pending_question_queue_roundtrips_without_granting_execution():
    from app.schemas.consultation_parent import ConsultationParent, ParentQuestion, ParentTask
    from app.services.consultation_result_service import finalize_result

    p = ConsultationParent(
        tasks=[
            ParentTask(task_id="task-a", goal="skin", version=1, status="waiting_user"),
            ParentTask(task_id="task-b", goal="product", version=1, status="waiting_user"),
        ],
        pending_questions=[
            ParentQuestion(
                task_id="task-a",
                goal="skin",
                version=1,
                text="어떤 상황인가요?",
                input_key="situation",
            ),
            ParentQuestion(
                task_id="task-b",
                goal="product",
                version=1,
                text="어떤 제품인가요?",
                input_key="selection",
            ),
        ],
    )
    r = ChatResponse(answer="확인이 필요해요", products=[])
    r._consultation_parent = p
    finalize_result(r)
    assert r.consultation.status == "waiting_user" and r.consultation.has_pending_input
    saved = updated_context({}, r)
    restored = prepare_request(ChatRequest(message="첫 질문에 답할게요"), saved, [])
    assert len(restored._consultation_parent.pending_questions) == 2
    assert restored._consultation_parent.question.task_id == "task-a"
    assert restored.ar_context is None and r.ar_result is None and r.memory_proposal is None
    assert restore_response(r.answer, display_payload(r)).consultation == r.consultation
