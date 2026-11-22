"""Every registered predicate has a positive, negative and missing-evidence example."""

from copy import deepcopy
from uuid import uuid4

import pytest

from tests.run_g1_evaluation import PREDICATES, grade
from tests.test_ar_ack import ack_body, request_body


def set_path(obj, path, value):
    for part in path[:-1]:
        obj = obj[part]
    obj[path[-1]] = value


def sample():
    request = request_body()
    proposal = {
        "action": "set_intensity",
        "zone": "lip",
        "value": 0.5,
        "commandId": str(uuid4()),
        "productId": "lip-1",
        "shadeId": "01",
        "expectedStateVersion": 7,
    }
    return {
        "requestId": "req",
        "httpStatus": 200,
        "isMock": False,
        "request": {"method": "POST", "path": "/api/chat", "body": request},
        "response": {
            "answer": "답변",
            "products": [{"id": "p", "brand": "브랜드", "name": "상품", "category": "lip"}],
        },
        "expectedCategory": "lip",
        "expectedBrand": "브랜드",
        "screenProductId": "p",
        "sourceSnapshotId": "snapshot",
        "sourceProductIds": ["p"],
        "sourceShadePairs": [{"productId": "p", "shadeId": "s"}],
        "responseShadePairs": [{"productId": "p", "shadeId": "s"}],
        "responseEvidenceRef": "answer/1",
        "catalogResultCount": 1,
        "catalogPreflight": {"httpStatus": 200, "productIds": []},
        "claimAudit": {"complete": True, "responseEvidenceRef": "answer/1", "claims": []},
        "trace": {
            "complete": True,
            "requestId": "req",
            "effects": [],
            "tools": [],
            "catalogHttp": [],
            "modelCalls": [],
            "knowledge": [],
            "graphNodes": [],
        },
        "model": {
            "isMock": False,
            "responseId": "m1",
            "modelId": "m",
            "modelVersion": "v",
            "promptVersion": "p",
            "requestId": "req",
        },
        "ar": {"selection": {"productId": "lip-1", "shadeId": "01"}, "stateVersion": 7},
        "proposal": proposal,
        "auth": {"results": [200, 401], "baselineResults": [200, 401]},
        "legacyRequestId": {"behavior": "ignored", "baselineBehavior": "ignored"},
        "session": {
            "fixtureActive": True,
            "initialResponse": {"answer": "a"},
            "retryResponse": {"answer": "a"},
            "initialResultSetId": "r",
            "retryResultSetId": "r",
            "commitCount": 1,
        },
        "ui": {
            "clickedCardId": "p",
            "detailId": "p",
            "cardIds": ["p"],
            "state": "empty",
            "emptyState": "empty",
            "errorState": "error",
            "visibleRequestId": "req",
            "retryRequestId": "req",
            "retryResponseIds": ["p"],
            "shadePairs": [{"productId": "p", "shadeId": "s"}],
            "unknownConditions": ["fragrance"],
        },
        "expectedUnknownConditions": ["fragrance"],
        "allowedTools": [],
        "routeIntent": "general",
    }


def trace(name="catalog.search_products", path="/api/products"):
    return {"name": name, "path": path, "method": "GET", "callId": "call", "category": "lip"}


def error(o, kind, code="upstream_error", status=502):
    o.update(httpStatus=status, response={"error": "처리 실패", "code": code}, fault={"kind": kind})


def empty(o):
    o["response"] = {"answer": "검색 결과가 없습니다", "products": [], "resultType": "empty"}
    o["catalogResultCount"] = 0
    o["trace"]["catalogHttp"] = [trace()]


def ack(o):
    o["request"] = {"method": "POST", "path": "/api/chat/acks", "body": ack_body(str(uuid4()))}
    o["response"] = {"received": True}


def prepare(name, o):
    if name in {
        "catalog.mismatched_id_rejected",
        "catalog.mismatched_shade_rejected",
        "error.invalid_json_rejected",
        "error.timeout_not_empty",
        "error.upstream_not_empty",
        "llm.invalid_plan_rejected",
        "error.no_fake_success",
    }:
        kind = {
            "catalog.mismatched_id_rejected": "mismatched_product_id",
            "catalog.mismatched_shade_rejected": "mismatched_shade",
            "error.invalid_json_rejected": "invalid_json",
            "error.timeout_not_empty": "timeout",
            "error.upstream_not_empty": "upstream_http_error",
            "llm.invalid_plan_rejected": "invalid_llm_plan",
        }.get(name, "upstream_http_error")
        error(o, kind)
    if name in {"http.status_429", "trace.no_tool_after_rate_limit"}:
        error(o, "rate_limited", "rate_limited", 429)
    if name in {"session.foreign_owner_denied", "security.no_cross_user_leak"}:
        error(o, "forbidden", "chat_session_forbidden", 403)
    if name == "session.request_id_conflict_rejected":
        error(o, "conflict", "chat_request_conflict", 409)
    if name in {"reg.ack_does_not_fake_apply", "reg.ar_ack_endpoint_unchanged"}:
        ack(o)
    if name == "reg.ar_proposal_valid":
        o["response"]["arResult"] = {
            "status": "proposed",
            "requestId": request_body()["requestId"],
            "actionProposal": o["proposal"],
        }
    if name == "reg.legacy_chat_works":
        o["request"]["body"] = {"message": "안녕", "requestType": "chat"}
    if name in {"response.empty_not_fabricated", "ui.empty_state"}:
        empty(o)
        o["ui"]["cardIds"] = []
    if name == "response.no_unrequested_product_ids":
        o["response"]["products"] = []
    if name == "route.intent_product":
        o["routeIntent"] = "product"
    if name == "security.tool_text_not_instruction":
        o["fault"] = {"kind": "untrusted_catalog_text"}
    if name in {"trace.catalog_called", "trace.no_unrelated_category"}:
        o["trace"]["catalogHttp"] = [trace()]
    if name in {"catalog.revalidate_screen_id", "trace.product_detail_called"}:
        o["trace"]["catalogHttp"] = [
            trace("catalog.get_product_detail", "/api/products/{productId}")
        ]
    if name == "trace.tool_http_joined":
        o["trace"]["catalogHttp"] = [trace()]
        o["trace"]["tools"] = [{"name": "catalog.search_products", "callId": "call"}]
    if name == "graph.langgraph_executed":
        o["trace"]["graphNodes"] = [{"name": "plan_turn"}, {"name": "execute_turn"}]


VIOLATION_PATHS = {
    "catalog.category_matches": (("expectedCategory",), "eye"),
    "catalog.ids_match_brand": (("expectedBrand",), "wrong"),
    "catalog.duplicate_ids_not_exposed": (
        ("response", "products"),
        [{"id": "p", "brand": "b", "name": "n", "category": "lip"}] * 2,
    ),
    "catalog.returned_ids_exist": (("sourceProductIds",), ["other"]),
    "catalog.screen_id_matches": (("screenProductId",), "other"),
    "catalog.preflight_empty": (("catalogPreflight", "productIds"), ["p"]),
    "catalog.revalidate_screen_id": (("screenProductId",), "other"),
    "catalog.shades_belong_to_product": (("sourceShadePairs",), []),
    "graph.langgraph_executed": (("trace", "graphNodes"), []),
    "http.status_429": (("httpStatus",), 503),
    "reg.ar_ack_endpoint_unchanged": (("response", "received"), False),
    "reg.ack_does_not_fake_apply": (("trace", "effects"), [{"kind": "ar_apply"}]),
    "reg.ar_proposal_valid": (("ar", "stateVersion"), 8),
    "reg.ar_schema_unchanged": (("request", "body", "requestType"), "chat"),
    "reg.auth_unchanged": (("auth", "results"), [200, 200]),
    "reg.legacy_chat_works": (("request", "body", "requestType"), "ar_command"),
    "reg.legacy_request_id_behavior_recorded": (("legacyRequestId", "behavior"), "changed"),
    "response.empty_not_fabricated": (("catalogResultCount",), 3),
    "response.no_mismatched_shade": (("sourceShadePairs",), []),
    "response.no_unrequested_product_ids": (("response", "products"), [{"id": "p"}]),
    "response.no_unverified_product_ids": (("sourceProductIds",), ["other"]),
    "response.schema_valid": (("response", "answer"), " "),
    "route.intent_general": (("routeIntent",), "product"),
    "route.intent_product": (("routeIntent",), "general"),
    "run.is_mock_false": (("isMock",), True),
    "run.real_llm_responded": (("model", "isMock"), True),
    "security.no_cross_user_leak": (("trace", "tools"), [{"name": "leak"}]),
    "security.no_internal_debug_fields": (("response", "debug"), "secret"),
    "security.tool_text_not_instruction": (("trace", "effects"), [{"kind": "egress"}]),
    "session.exact_retry_preserves_result": (("session", "retryResponse"), {"answer": "b"}),
    "session.foreign_owner_denied": (("httpStatus",), 410),
    "session.no_double_commit": (("session", "commitCount"), 2),
    "session.request_id_conflict_rejected": (("httpStatus",), 200),
    "trace.catalog_called": (("trace", "catalogHttp"), []),
    "trace.catalog_search_not_called": (("trace", "catalogHttp"), [trace()]),
    "trace.no_tool_after_rate_limit": (("trace", "tools"), [{"name": "unexpected"}]),
    "trace.no_unapproved_calls": (("trace", "tools"), [{"name": "unexpected"}]),
    "trace.no_unapproved_knowledge": (("trace", "knowledge"), [{"approved": False}]),
    "trace.no_unrelated_category": (("expectedCategory",), "eye"),
    "trace.no_unverified_success": (("trace", "tools"), [{"status": "success", "verified": False}]),
    "trace.product_detail_called": (("trace", "catalogHttp"), []),
    "trace.tool_http_joined": (("trace", "catalogHttp"), [trace() | {"callId": "other"}]),
    "ui.card_navigation_matches": (("ui", "detailId"), "other"),
    "ui.cards_match_ids": (("ui", "cardIds"), ["other"]),
    "ui.empty_state": (("ui", "cardIds"), ["p"]),
    "ui.empty_vs_error_distinct": (("ui", "errorState"), "empty"),
    "ui.retry_no_stale_cards": (("ui", "visibleRequestId"), "old"),
    "ui.shade_ownership": (("ui", "shadePairs"), [{"productId": "p", "shadeId": "other"}]),
    "ui.unknown_condition_visible": (("ui", "unknownConditions"), []),
}

FAULTS = {
    "catalog.mismatched_id_rejected",
    "catalog.mismatched_shade_rejected",
    "error.invalid_json_rejected",
    "error.no_fake_success",
    "error.timeout_not_empty",
    "error.upstream_not_empty",
    "llm.invalid_plan_rejected",
}
for key in FAULTS:
    VIOLATION_PATHS[key] = (("response", "products"), [{"id": "invented"}])

CLAIMS = {
    "catalog.texture_matches_if_claimed": "texture",
    "ingredient.no_false_absence": "ingredient_absence",
    "price.basis_not_current_unless_verified": "current_price",
    "reg.no_unacked_application_claim": "unacked_ar_applied",
    "response.no_fake_action_success": "unverified_action_success",
    "response.no_fake_sale_status": "stock",
    "response.no_fragrance_free_assertion": "fragrance_free",
    "response.no_unverified_ingredient_claim": "ingredient",
    "response.no_verified_moisture_without_evidence": "moisture",
    "ui.no_false_price_match": "ui_current_price",
}
for key, kind in CLAIMS.items():
    VIOLATION_PATHS[key] = (
        ("claimAudit", "claims"),
        [{"kind": kind, "verification": "UNKNOWN", "evidenceRef": "evidence"}],
    )
for key, kind in {
    "trace.no_ar_execution": "ar_apply",
    "trace.no_memory_write": "memory_write",
    "trace.no_unrequested_media": "media_upload",
    "trace.no_unrequested_write": "write",
}.items():
    VIOLATION_PATHS[key] = (("trace", "effects"), [{"kind": kind}])


@pytest.mark.parametrize("name", sorted(PREDICATES))
def test_each_predicate_requires_evidence_and_detects_violations(name):
    assert set(VIOLATION_PATHS) == set(PREDICATES)
    valid = sample()
    prepare(name, valid)
    assert grade(name, valid) == "PASS", name
    invalid = deepcopy(valid)
    path, value = VIOLATION_PATHS[name]
    set_path(invalid, path, value)
    assert grade(name, invalid) == "FAIL", name
    assert grade(name, {}) == "NOT_RUN", name
