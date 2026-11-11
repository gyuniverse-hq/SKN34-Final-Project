"""Read-only, test-only observation hooks for the pinned #229 service.

No expected cases are accepted by these helpers. Install hooks only for a
single isolated run; they wrap actual calls and never replace their results.
"""

import json
from contextlib import ExitStack
from copy import deepcopy
from hashlib import sha256
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

import httpx

_PRIVATE_KEYS = {
    "authorization",
    "cookie",
    "setcookie",
    "token",
    "sessiontoken",
    "tokenhash",
    "accesstoken",
    "refreshtoken",
    "apikey",
    "secret",
    "password",
    "owner",
    "ownerhash",
    "sessionsecret",
    "credential",
    "credentials",
}


def redact(value):
    """Return a detached JSON-compatible value with capability fields hidden."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if "".join(c for c in str(key).lower() if c.isalnum()) in _PRIVATE_KEYS
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [redact(item) for item in value]
    return deepcopy(value)


def _origin(value):
    parts = urlsplit(str(value))
    return parts.scheme.lower(), parts.hostname, parts.port


class ObservationCapture:
    """Intercept calls to the real interpreter and Catalog HTTP for one turn.

    The caller must serialize turns: these hooks temporarily patch process-wide
    methods. Enter/exit restores both functions, including on failure.
    """

    def __init__(self, catalog_base):
        parts = urlsplit(catalog_base)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("A valid Catalog origin is required")
        self.catalog_origin = _origin(catalog_base)
        self.trace = {}
        self._stack = None

    def __enter__(self):
        from unittest.mock import patch

        from app.services import chat_service

        self._stack = ExitStack()
        original_interpret = chat_service.interpret_beauty
        original_request = httpx.AsyncClient.request
        trace = self.trace
        origin = self.catalog_origin

        async def observed_interpret(*args, **kwargs):
            plan = await original_interpret(*args, **kwargs)
            trace["plan"] = redact(plan)
            return plan

        async def observed_request(client, method, url, *args, **kwargs):
            try:
                target = _origin(url)
            except (ValueError, TypeError):
                target = None
            if target != origin:
                return await original_request(client, method, url, *args, **kwargs)
            parsed = urlsplit(str(url))
            entry = {"method": str(method).upper(), "path": parsed.path}
            if parsed.query:
                entry["query"] = [
                    redact({key: value})
                    for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                ]
            if kwargs.get("params") is not None:
                entry["params"] = redact(dict(kwargs["params"]))
            if "json" in kwargs and kwargs["json"] is not None:
                entry["request"] = redact(kwargs["json"])
            trace.setdefault("catalogRequests", []).append(entry)
            claim = parsed.path == "/api/catalog/ingredient-claims/search"
            if claim and isinstance(kwargs.get("json"), dict):
                trace.setdefault("claimRequests", []).append(redact(kwargs["json"]))
            try:
                response = await original_request(client, method, url, *args, **kwargs)
            except httpx.HTTPError as exc:
                entry["transportError"] = type(exc).__name__
                if claim:
                    trace.setdefault("claimResponses", []).append(
                        {"transportError": type(exc).__name__}
                    )
                raise
            entry["httpStatus"] = response.status_code
            try:
                response_data = redact(response.json())
            except (ValueError, UnicodeDecodeError):
                entry["responseUnavailable"] = True
            else:
                entry["response"] = response_data
            if claim:
                result = {"httpStatus": response.status_code}
                if "response" in entry:
                    result["response"] = deepcopy(entry["response"])
                trace.setdefault("claimResponses", []).append(result)
            return response

        try:
            self._stack.enter_context(
                patch.object(chat_service, "interpret_beauty", observed_interpret)
            )
            self._stack.enter_context(patch.object(httpx.AsyncClient, "request", observed_request))
        except BaseException:
            self._stack.close()
            raise
        return self

    def __exit__(self, *exc):
        return self._stack.__exit__(*exc)


def _copy_if_present(target, target_key, source, source_key):
    if source_key in source:
        target[target_key] = redact(source[source_key])


def project_session(raw):
    """Project observed Redis JSON only; absent/malformed input is not a state."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    state = json.loads(raw) if isinstance(raw, str) else deepcopy(raw)
    if not isinstance(state, dict):
        raise ValueError("Invalid Redis state")
    for key in ("sessionId", "stateVersion", "resultSetId", "context"):
        if key not in state:
            raise ValueError("Incomplete Redis state")
    context = state["context"]
    if not isinstance(context, dict):
        raise ValueError("Invalid Redis context")
    result = {"exists": True}
    for key in ("sessionId", "stateVersion", "resultSetId", "lastRequestId"):
        _copy_if_present(result, key, state, key)
    for key in ("candidateIds", "scopeIds", "selectedProductId", "shadeSelections"):
        _copy_if_present(result, key, context, key)
    filters = context.get("filters")
    if filters is not None:
        if not isinstance(filters, dict):
            raise ValueError("Invalid Redis filters")
        for key in ("ingredientConditions", "maxPriceKRW", "fragranceFree", "moisturizing"):
            _copy_if_present(result, key, filters, key)
    option = state.get("optionContext")
    if option is not None:
        if not isinstance(option, dict):
            raise ValueError("Invalid Redis option context")
        _copy_if_present(result, "optionSelections", option, "selections")
        _copy_if_present(result, "priceBasis", option, "priceBasis")
        _copy_if_present(result, "requireInStock", option, "requireInStock")
        _copy_if_present(result, "categoryId", option, "categoryId")
    return result


async def snapshot_session(client, *, owner=None, request_id=None, session_id=None, fresh=False):
    """Read Redis only. None means unknown; exists=false needs a confirmed read.

    For an explicitly fresh session the request-index lookup establishes that
    this request has no stored session. Never infer absence from an exception.
    """
    if client is None:
        return None
    try:
        if session_id is None:
            if not (fresh and owner and request_id):
                return None
            request_uuid = UUID(str(request_id))
            owner_hash = sha256(owner.encode()).hexdigest()
            indexed = await client.get(f"vishue:chat:request:{owner_hash}:{request_uuid}")
            if indexed is None:
                return {"exists": False}
            session_id = indexed.decode("utf-8") if isinstance(indexed, bytes) else indexed
        session_uuid = UUID(str(session_id))
        raw = await client.get(f"vishue:chat:session:{session_uuid}")
        if raw is None:
            return {"exists": False}
        projected = project_session(raw)
        if projected["sessionId"] != str(session_uuid):
            return None
        return projected
    except Exception:
        # Bad state, transport failure and access failure all remain unobserved.
        return None
