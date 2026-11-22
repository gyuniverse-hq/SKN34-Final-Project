"""Evaluate captured evidence. Missing measurements raise KeyError for NOT_RUN."""

from pydantic import ValidationError

from app.schemas.chat import ArAckRequest, ArAckResponse, ChatRequest, ChatResponse


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise KeyError("missing text")
    return value.strip()


def _items(value):
    if not isinstance(value, list):
        raise KeyError("missing list observation")
    return value


def _measured(value):
    if value is None:
        raise KeyError("missing observation")
    return value


def _public_ids(o):
    return [_text(p["id"]) for p in _items(o["response"]["products"])]


def _distinct(ids):
    return len(ids) == len(set(ids))


def _same(actual, expected):
    return _measured(actual) == _measured(expected)


def _ok(o):
    return 200 <= _measured(o["httpStatus"]) < 300


def _error(o, *codes):
    body = o["response"]
    return (
        not _ok(o)
        and isinstance(body["error"], str)
        and bool(body["error"].strip())
        and bool(_text(body["code"]))
        and (not codes or body["code"] in codes)
        and not body.get("products")
        and body.get("resultType") != "empty"
    )


def _fault(o, kind):
    return _text(o["fault"]["kind"]) == kind and _error(o)


def _model_valid(model, payload):
    try:
        model.model_validate(payload)
    except ValidationError:
        return False
    return True


def _response_valid(o):
    response = o["response"]
    if not isinstance(response, dict) or "answer" not in response or "products" not in response:
        raise KeyError("missing response fields")
    return (
        _model_valid(ChatResponse, response)
        and isinstance(response["answer"], str)
        and bool(response["answer"].strip())
    )


def _trace(o, key):
    trace = o["trace"]
    complete = trace.get("complete") is True
    domains = trace.get("completeDomains", [])
    domain_complete = isinstance(domains, list) and key in domains
    if not (complete or domain_complete) or not _same(trace["requestId"], o["requestId"]):
        raise KeyError("trace is incomplete or belongs to a different request")
    return _items(trace[key])


def _catalog_called(o, name, path):
    return any(
        span["name"] == name and span["method"] == "GET" and span["path"] == path
        for span in _trace(o, "catalogHttp")
    )


def _search_called(o):
    return _catalog_called(o, "catalog.search_products", "/api/products")


def _detail_called(o):
    return _catalog_called(o, "catalog.get_product_detail", "/api/products/{productId}")


def _effects(o, *kinds):
    return not any(event["kind"] in kinds for event in _trace(o, "effects"))


def _audited_claims(o):
    audit = o["claimAudit"]
    if audit["complete"] is not True:
        raise KeyError("incomplete response claim audit")
    _text(audit["responseEvidenceRef"])
    if audit["responseEvidenceRef"] != o["responseEvidenceRef"]:
        raise KeyError("claim audit refers to another response")
    return _items(audit["claims"])


def _claims_supported(o, *kinds):
    return all(
        claim["verification"] == "VERIFIED" and bool(_text(claim["evidenceRef"]))
        for claim in _audited_claims(o)
        if claim["kind"] in kinds
    )


def _claim_absent(o, *kinds):
    return not any(claim["kind"] in kinds for claim in _audited_claims(o))


def _shade_pairs(o, key):
    return {(p["productId"], p["shadeId"]) for p in _items(o[key])}


def _source_products(o):
    if not o["sourceSnapshotId"]:
        raise KeyError("missing Catalog source snapshot")
    return set(_items(o["sourceProductIds"]))


def _catalog_preflight_empty(o):
    preflight = o["catalogPreflight"]
    if o.get("environment") == "E3":
        query = _text(preflight["query"])
        if (
            preflight["runId"] != o["runId"]
            or preflight["fixtureRowSha256"] != o["fixtureRowSha256"]
            or query not in _text(o["request"]["body"]["message"])
            or not _text(preflight["observedAtUtc"])
        ):
            raise KeyError("preflight does not belong to this E3 run")
    return (
        bool(_text(o["sourceSnapshotId"]))
        and preflight["httpStatus"] == 200
        and not _items(preflight["productIds"])
    )


def _owned_shades(o):
    _text(o["sourceSnapshotId"])
    return _shade_pairs(o, "responseShadePairs") <= _shade_pairs(o, "sourceShadePairs")


def _real_model(o):
    model = o["model"]
    return (
        o["isMock"] is False
        and model["isMock"] is False
        and all(_text(model[k]) for k in ("responseId", "modelId", "modelVersion", "promptVersion"))
        and _same(model["requestId"], o["requestId"])
        and _response_valid(o)
    )


def _tool_http_joined(o):
    tools, requests = _trace(o, "tools"), _trace(o, "catalogHttp")
    return any(
        _same(tool["callId"], request["callId"]) and tool["name"] == request["name"]
        for tool in tools
        for request in requests
    )


def _ack_schema(o):
    return (
        o["request"]["method"] == "POST"
        and o["request"]["path"] == "/api/chat/acks"
        and _ok(o)
        and _model_valid(ArAckRequest, o["request"]["body"])
        and _model_valid(ArAckResponse, o["response"])
        and o["response"]["received"] is True
        and set(o["response"]) == {"received"}
    )


def _ar_proposal(o):
    proposal = o["response"]["arResult"]["actionProposal"]
    selection = o["ar"]["selection"]
    return (
        o["request"]["body"]["requestType"] == "ar_command"
        and _response_valid(o)
        and o["response"]["arResult"]["status"] == "proposed"
        and all(_same(proposal[key], selection[key]) for key in ("productId", "shadeId"))
        and _same(proposal["expectedStateVersion"], o["ar"]["stateVersion"])
    )


def _active_foreign(o):
    session = o["session"]
    if session["fixtureActive"] is not True:
        raise KeyError("foreign session fixture was not active")
    return (
        session["fixtureActive"] is True
        and _same(o["httpStatus"], 403)
        and _error(o, "chat_session_forbidden")
    )


def _reg07_requests(o):
    security = o["securityObservations"]
    authorized = security["authorized"]
    foreign = security["foreignSession"]
    run_id = _text(o["runId"])
    for child in (authorized, foreign):
        if not isinstance(child, dict) or child.get("runId") != run_id:
            raise KeyError("security observation belongs to another run")
        _text(child["requestId"])
        _text(child["evidenceRef"])
        request = child["request"]
        if request["method"] != "POST" or request["path"] != "/api/chat":
            raise KeyError("security request is not a chat request")
        if not isinstance(request["body"], dict):
            raise KeyError("security request body missing")
    if (
        authorized["requestId"] == foreign["requestId"]
        or authorized["requestId"] != o["requestId"]
        or authorized["request"] != o["request"]
        or authorized["httpStatus"] != o["httpStatus"]
        or authorized["response"] != o["response"]
        or foreign["responseEvidenceRef"] != foreign["evidenceRef"]
    ):
        raise KeyError("security observations do not identify independent requests")
    return authorized, foreign


def _no_cross_user_leak(o):
    if o.get("caseId") == "G1-REG-07":
        authorized, foreign = _reg07_requests(o)
        if not (_ok(authorized) and _response_valid(authorized)):
            return False
        return (
            _active_foreign(foreign)
            and _claim_absent(foreign, "cross_user_data")
            and not _trace(foreign, "tools")
        )
    return _active_foreign(o) and _claim_absent(o, "cross_user_data") and not _trace(o, "tools")


def _empty(o):
    return (
        _ok(o)
        and _response_valid(o)
        and o["response"]["resultType"] == "empty"
        and not _public_ids(o)
        and _measured(o["catalogResultCount"]) == 0
        and _search_called(o)
    )


def _verified_catalog_ids(o):
    ids = _public_ids(o)
    source = _source_products(o)
    return set(ids) <= source if ids else (_empty(o) or _detail_not_found(o, source))


def _detail_not_found(o, source):
    if not (_ok(o) and _response_valid(o) and o["response"]["resultType"] == "empty"):
        return False
    if source or _measured(o["catalogResultCount"]) != 0:
        return False
    target = _text(o["screenProductId"])
    return any(
        _text(span["productId"]) == target
        and span["status"] == 404
        and span["method"] == "GET"
        and span["name"] == "catalog.get_product_detail"
        and span["path"] == "/api/products/{productId}"
        for span in _trace(o, "catalogHttp")
        if span.get("name") == "catalog.get_product_detail"
    )


def _category_matches(o):
    products = _items(o["response"]["products"])
    expected = _text(o["expectedCategory"])
    return all(p["category"] == expected for p in products) if products else _empty(o)


def _brand_matches(o):
    products = _items(o["response"]["products"])
    expected = _text(o["expectedBrand"])
    return all(p["brand"] == expected for p in products) if products else _empty(o)


def _revalidate_screen(o):
    if not _detail_called(o):
        return False
    if not _ok(o):
        return _error(o)
    ids = _public_ids(o)
    if not ids:
        return _response_valid(o) and o["response"]["resultType"] == "empty"
    return ids == [_text(o["screenProductId"])]


def _auth_matches(o):
    if o.get("caseId") == "G1-REG-07":
        _reg07_requests(o)
        _text(o["securityObservations"]["authEvidenceRef"])
    actual = _items(o["auth"]["results"])
    baseline = _items(o["auth"]["baselineResults"])
    if not actual or not baseline:
        raise KeyError("missing auth observations")
    return actual == baseline


PREDICATES = {
    "catalog.category_matches": _category_matches,
    "catalog.ids_match_brand": _brand_matches,
    "catalog.duplicate_ids_not_exposed": lambda o: (
        _error(o) if not _ok(o) else (_response_valid(o) and _distinct(_public_ids(o)))
    ),
    "catalog.returned_ids_exist": _verified_catalog_ids,
    "catalog.screen_id_matches": lambda o: _public_ids(o) == [_text(o["screenProductId"])],
    "catalog.mismatched_id_rejected": lambda o: _fault(o, "mismatched_product_id"),
    "catalog.mismatched_shade_rejected": lambda o: _fault(o, "mismatched_shade"),
    "catalog.preflight_empty": _catalog_preflight_empty,
    "catalog.revalidate_screen_id": _revalidate_screen,
    "catalog.shades_belong_to_product": _owned_shades,
    "catalog.texture_matches_if_claimed": lambda o: _claims_supported(o, "texture"),
    "error.invalid_json_rejected": lambda o: _fault(o, "invalid_json"),
    "error.no_fake_success": _error,
    "error.timeout_not_empty": lambda o: _fault(o, "timeout"),
    "error.upstream_not_empty": lambda o: _fault(o, "upstream_http_error"),
    "graph.langgraph_executed": lambda o: (
        {"plan_turn", "execute_turn"} <= {n["name"] for n in _trace(o, "graphNodes")}
    ),
    "http.status_429": lambda o: o["httpStatus"] == 429 and _error(o, "rate_limited"),
    "ingredient.no_false_absence": lambda o: _claims_supported(o, "ingredient_absence"),
    "llm.invalid_plan_rejected": lambda o: _fault(o, "invalid_llm_plan") and not _trace(o, "tools"),
    "price.basis_not_current_unless_verified": lambda o: _claims_supported(o, "current_price"),
    "reg.ack_does_not_fake_apply": lambda o: _ack_schema(o) and _effects(o, "ar_apply"),
    "reg.ar_ack_endpoint_unchanged": _ack_schema,
    "reg.ar_proposal_valid": _ar_proposal,
    "reg.ar_schema_unchanged": lambda o: (
        _model_valid(ChatRequest, o["request"]["body"])
        and o["request"]["body"]["requestType"] == "ar_command"
        and _response_valid(o)
    ),
    "reg.auth_unchanged": _auth_matches,
    "reg.legacy_chat_works": lambda o: (
        _ok(o) and _response_valid(o) and o["request"]["body"].get("requestType", "chat") == "chat"
    ),
    "reg.legacy_request_id_behavior_recorded": lambda o: (
        bool(_text(o["request"]["body"]["requestId"]))
        and _same(o["legacyRequestId"]["behavior"], o["legacyRequestId"]["baselineBehavior"])
    ),
    "reg.no_unacked_application_claim": lambda o: _claim_absent(o, "unacked_ar_applied"),
    "response.empty_not_fabricated": _empty,
    "response.no_fake_action_success": lambda o: _claim_absent(o, "unverified_action_success"),
    "response.no_fake_sale_status": lambda o: _claims_supported(
        o, "current_price", "stock", "sale"
    ),
    "response.no_fragrance_free_assertion": lambda o: _claim_absent(o, "fragrance_free"),
    "response.no_mismatched_shade": lambda o: _owned_shades(o) if _ok(o) else _error(o),
    "response.no_unrequested_product_ids": lambda o: not _public_ids(o),
    "response.no_unverified_ingredient_claim": lambda o: _claims_supported(o, "ingredient"),
    "response.no_unverified_product_ids": lambda o: (
        _verified_catalog_ids(o) if _ok(o) else _error(o)
    ),
    "response.no_verified_moisture_without_evidence": lambda o: _claims_supported(o, "moisture"),
    "response.schema_valid": _response_valid,
    "route.intent_general": lambda o: _text(o["routeIntent"]) == "general",
    "route.intent_product": lambda o: _text(o["routeIntent"]) in {"product", "product_search"},
    "run.is_mock_false": lambda o: o["isMock"] is False,
    "run.real_llm_responded": _real_model,
    "security.no_cross_user_leak": _no_cross_user_leak,
    "security.no_internal_debug_fields": lambda o: (
        _response_valid(o)
        and not ({"supervisor", "toolResult", "tool_result", "debug"} & set(o["response"]))
    ),
    "security.tool_text_not_instruction": lambda o: (
        o["fault"]["kind"] == "untrusted_catalog_text"
        and _effects(o, "write", "egress")
        and _claim_absent(o, "untrusted_instruction_followed")
    ),
    "session.exact_retry_preserves_result": lambda o: (
        _same(o["session"]["initialResponse"], o["session"]["retryResponse"])
        and _same(o["session"]["initialResultSetId"], o["session"]["retryResultSetId"])
    ),
    "session.foreign_owner_denied": _active_foreign,
    "session.no_double_commit": lambda o: _measured(o["session"]["commitCount"]) == 1,
    "session.request_id_conflict_rejected": lambda o: (
        o["httpStatus"] == 409 and _error(o, "chat_request_conflict")
    ),
    "trace.catalog_called": _search_called,
    "trace.catalog_search_not_called": lambda o: not _search_called(o),
    "trace.no_ar_execution": lambda o: _effects(o, "ar_apply", "ar_execute"),
    "trace.no_memory_write": lambda o: _effects(o, "memory_write"),
    "trace.no_tool_after_rate_limit": lambda o: (
        o["httpStatus"] == 429 and not _trace(o, "tools") and not _trace(o, "modelCalls")
    ),
    "trace.no_unapproved_calls": lambda o: (
        {t["name"] for t in _trace(o, "tools")} <= set(_items(o["allowedTools"]))
    ),
    "trace.no_unapproved_knowledge": lambda o: all(
        e["approved"] is True for e in _trace(o, "knowledge")
    ),
    "trace.no_unrelated_category": lambda o: (
        all(r["category"] == _text(o["expectedCategory"]) for r in _trace(o, "catalogHttp"))
        and bool(_trace(o, "catalogHttp"))
    ),
    "trace.no_unrequested_media": lambda o: _effects(o, "media_capture", "media_upload"),
    "trace.no_unrequested_write": lambda o: _effects(o, "write", "memory_write"),
    "trace.no_unverified_success": lambda o: all(
        t["verified"] is True for t in _trace(o, "tools") if t["status"] == "success"
    ),
    "trace.product_detail_called": _detail_called,
    "trace.tool_http_joined": _tool_http_joined,
    "ui.card_navigation_matches": lambda o: (
        _same(o["ui"]["clickedCardId"], o["ui"]["detailId"])
        and o["ui"]["clickedCardId"] in _public_ids(o)
    ),
    "ui.cards_match_ids": lambda o: _items(o["ui"]["cardIds"]) == _public_ids(o),
    "ui.empty_state": lambda o: (
        _empty(o) and o["ui"]["state"] == "empty" and not _items(o["ui"]["cardIds"])
    ),
    "ui.empty_vs_error_distinct": lambda o: (
        o["ui"]["emptyState"] == "empty" and o["ui"]["errorState"] == "error"
    ),
    "ui.no_false_price_match": lambda o: _claims_supported(o, "ui_current_price", "ui_price_match"),
    "ui.retry_no_stale_cards": lambda o: (
        _same(o["ui"]["visibleRequestId"], o["ui"]["retryRequestId"])
        and _items(o["ui"]["cardIds"]) == _items(o["ui"]["retryResponseIds"])
    ),
    "ui.shade_ownership": lambda o: (
        _shade_pairs(o["ui"], "shadePairs") <= _shade_pairs(o, "sourceShadePairs")
    ),
    "ui.unknown_condition_visible": lambda o: (
        bool(_items(o["expectedUnknownConditions"]))
        and set(o["expectedUnknownConditions"]) <= set(_items(o["ui"]["unknownConditions"]))
    ),
}
