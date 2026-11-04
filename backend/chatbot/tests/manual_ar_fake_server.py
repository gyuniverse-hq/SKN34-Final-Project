"""Isolated guest-only AR test server; never use it for production or real products.

Run from backend/chatbot with ``python -m tests.manual_ar_fake_server``.
VISHUE_FAKE_ADMIN must contain a strong, random 32+ character management secret.
The server defaults to loopback. LAN binding requires an explicit private PC IP and
one private device IP. All traffic is plain HTTP; use only an isolated trusted LAN.
"""

import argparse
import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import re
import socket
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException

from app.core.auth import ChatPrincipal, chat_principal
from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.repositories.ar_command_repository import MemoryArRequestRepository
from app.routers.chat import router
from app.schemas.catalog import CatalogProduct
from app.schemas.chat import ArAckRequest, ChatRequest, ChatResponse
from app.services.ar_command_service import _PERCENT
from app.services.chat_service import ChatService, get_chat_service

PRODUCT = {
    "id": "demo-lip-matte",
    "brand": "FAKE TEST DATA",
    "name": "FAKE TEST LIP - NOT A REAL PRODUCT",
    "nameKo": "가상 테스트 립 - 실제 상품 아님",
    "category": "lip",
    "makeupZone": "lip",
    "texture": "matte",
    "priceKRW": 0,
    "volume": "TEST ONLY",
    "description": "Fictional test data, not a real product.",
    "keyIngredients": [],
    "tags": ["demo", "FAKE", "TEST ONLY"],
    "imageUrl": "",
    "searchKeyword": "",
    "shades": [
        {
            "id": "demo-rose",
            "name": "FAKE TEST ROSE",
            "hex": "#C25A6E",
            "measureMethod": "placeholder",
            "colorSource": "placeholder",
        }
    ],
}
_GUEST = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_PRIVATE = tuple(
    ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def emit(event: str, **fields: Any) -> None:
    """Never include message text, headers, device identifiers or credentials."""
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


@dataclass
class State:
    pending_guest: bytes | None = None
    paired_guest: bytes | None = None
    chat_delay_ms: int = 0
    ack_delay_ms: int = 0
    next_chat_fail: bool = False
    next_ack_loss: bool = False
    next_stale_version: bool = False
    next_catalog_missing: bool = False
    next_shade_missing: bool = False
    model_calls: int = 0


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pair_pending: bool = False
    unpair: bool = False
    chat_delay_ms: int | None = Field(default=None, ge=0, le=30000)
    ack_delay_ms: int | None = Field(default=None, ge=0, le=30000)
    next_chat_fail: bool | None = None
    next_ack_loss: bool | None = None
    next_stale_version: bool | None = None
    next_catalog_missing: bool | None = None
    next_shade_missing: bool | None = None


class FakeLlm:
    configured = True

    def __init__(self, state: State) -> None:
        self.state = state

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self.state.model_calls += 1
        text = json.loads(messages[1]["content"])["message"]
        values = _PERCENT.findall(text)
        if "operation and zone" in messages[0]["content"]:
            # This test server recognizes only the scripted inputs; it never invokes a model.
            operation = {"조금 더 연하게": "down", "방금 변경 취소": "undo"}.get(text)
            if operation is None and len(values) == 1:
                operation = "set"
            return json.dumps(
                {"operation": operation or "clarify", "zone": "lip" if operation == "set" else None}
            )
        if len(values) != 1:
            reason = "value_required" if not values else "ambiguous_value"
            return json.dumps({"status": "clarification", "reason": reason})
        value = float(Decimal(values[0]) / 100)
        if not 0 <= value <= 1:
            return json.dumps({"status": "unsupported", "reason": "unsupported_action"})
        return json.dumps(
            {
                "status": "proposed",
                "action": {"action": "set_intensity", "zone": "lip", "value": value},
            }
        )


class FakeCatalog:
    def __init__(self, state: State) -> None:
        self.state = state

    async def get_product(self, product_id: str) -> CatalogProduct | None:
        if self.state.next_catalog_missing:
            self.state.next_catalog_missing = False
            return None
        if product_id != PRODUCT["id"]:
            return None
        product = CatalogProduct.model_validate(PRODUCT)
        if self.state.next_shade_missing:
            self.state.next_shade_missing = False
            return product.model_copy(update={"shades": []})
        return product


class FakeService(ChatService):
    def __init__(self, state: State) -> None:
        super().__init__(None, FakeLlm(state), FakeCatalog(state), MemoryArRequestRepository())
        self.state = state

    async def answer(self, req: ChatRequest, principal_key: str | None = None) -> ChatResponse:
        if req.request_type != "ar_command":
            raise ApiError(
                503, "General chat is disabled on this fake server", "fake_chat_disabled"
            )
        emit(
            "chat_request", requestId=str(req.request_id), stateVersion=req.ar_context.state_version
        )
        if self.state.chat_delay_ms:
            await asyncio.sleep(self.state.chat_delay_ms / 1000)
        try:
            if self.state.next_chat_fail:
                self.state.next_chat_fail = False
                raise ApiError(503, "Injected test failure", "fake_chat_failure")
            result = await super().answer(req, principal_key)
        except ApiError as exc:
            emit(
                "chat_response",
                requestId=str(req.request_id),
                status="error",
                code=exc.code,
                httpStatus=exc.status,
            )
            raise
        ar = result.ar_result
        proposal = ar.action_proposal if ar else None
        emit(
            "chat_response",
            requestId=str(req.request_id),
            status=ar.status if ar else None,
            commandId=str(proposal.command_id) if proposal else None,
            expectedStateVersion=proposal.expected_state_version if proposal else None,
        )
        return result

    async def _propose_ar(self, req: ChatRequest) -> ChatResponse:
        # Inject before the deduplication task completes, so identical retries stay identical.
        stale = self.state.next_stale_version
        self.state.next_stale_version = False
        response = await super()._propose_ar(req)
        proposal = response.ar_result.action_proposal if response.ar_result else None
        if stale and proposal:
            version = proposal.expected_state_version
            proposal.expected_state_version = version + 1 if version < 2**53 - 1 else version - 1
        return response

    def acknowledge_ar(self, principal_key: str, ack: ArAckRequest) -> None:
        super().acknowledge_ar(principal_key, ack)
        emit(
            "ack_received",
            requestId=str(ack.request_id),
            commandId=str(ack.command_id),
            status=ack.status,
            actualStateVersion=ack.actual_state_version,
        )
        if self.state.next_ack_loss:
            self.state.next_ack_loss = False
            # The ACK was recorded, but the client receives a failure and may resend only the ACK.
            raise ApiError(503, "Injected ACK response loss", "fake_ack_response_lost")


def create_fake_app(admin_secret: str, device_ip: str | None = None) -> FastAPI:
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", admin_secret):
        raise ValueError("VISHUE_FAKE_ADMIN must be 32-128 URL-safe characters")
    if device_ip is not None and not is_private_lan(device_ip):
        raise ValueError("device IP must be a private IPv4 address")
    state = State()
    service = FakeService(state)
    limiter = MemoryRateLimiter(limit=1000)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def restrict(request: Request, call_next):
        client = request.client.host if request.client else ""
        local = client == "127.0.0.1" or client == "::1"
        is_admin = request.url.path == "/__control"
        if (is_admin and not local) or (not local and client != device_ip):
            return JSONResponse({"error": "Forbidden", "code": "forbidden"}, status_code=403)
        if is_admin and request.headers.get("origin"):
            return JSONResponse({"error": "Forbidden", "code": "forbidden"}, status_code=403)
        if request.url.path.startswith("/api/") and request.headers.get("authorization"):
            return JSONResponse(
                {"error": "Guest-only test server", "code": "forbidden"}, status_code=403
            )
        if request.url.path == "/api/chat/acks" and state.ack_delay_ms:
            await asyncio.sleep(state.ack_delay_ms / 1000)
        response = await call_next(request)
        # Only report fixed routes, never arbitrary paths, query strings, bodies or headers.
        if request.url.path in {"/api/chat", "/api/chat/acks", "/api/products"}:
            method = request.method if request.method in {"GET", "POST"} else "OTHER"
            emit("http", path=request.url.path, method=method, status=response.status_code)
        return response

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return JSONResponse({"error": exc.message, "code": exc.code}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, __: RequestValidationError):
        return JSONResponse(
            {"error": "Invalid request", "code": "invalid_request"}, status_code=400
        )

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        return JSONResponse(
            {"error": "Not found", "code": "not_found"}, status_code=exc.status_code
        )

    @app.exception_handler(Exception)
    async def unexpected(_: Request, __: Exception):
        return JSONResponse({"error": "Internal test error", "code": "internal"}, status_code=500)

    async def fake_principal(request: Request) -> ChatPrincipal:
        guest = request.headers.get("x-vishue-anonymous-id", "")
        if not _GUEST.fullmatch(guest):
            raise ApiError(400, "Anonymous session is required", "invalid_request")
        digest = hashlib.sha256(guest.encode("ascii")).digest()
        if state.paired_guest is None:
            if state.pending_guest is None:
                state.pending_guest = digest
            raise ApiError(403, "Local pairing approval required", "fake_pairing_required")
        if not hmac.compare_digest(state.paired_guest, digest):
            raise ApiError(403, "Device is not paired", "fake_pairing_required")
        return ChatPrincipal(rate_limit_key="fake-guest:" + digest.hex())

    app.dependency_overrides[chat_principal] = fake_principal
    app.dependency_overrides[get_chat_service] = lambda: service
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.include_router(router)

    @app.get("/api/products")
    async def products(request: Request):
        ids = request.query_params.get("ids")
        category = request.query_params.get("category")
        q = request.query_params.get("q", "").casefold()
        matches = (not ids or PRODUCT["id"] in ids.split(",")) and (
            not category or category == "lip"
        )
        matches = matches and (
            not q or q in str(PRODUCT["name"]).casefold() or q in str(PRODUCT["nameKo"]).casefold()
        )
        return {"products": [PRODUCT] if matches else []}

    @app.get("/api/products/{product_id}")
    async def product(product_id: str):
        if product_id != PRODUCT["id"]:
            raise ApiError(404, "Product not found", "not_found")
        return {"product": PRODUCT}

    def admin(request: Request) -> None:
        supplied = request.headers.get("x-fake-admin", "")
        if not hmac.compare_digest(supplied.encode("utf-8"), admin_secret.encode("utf-8")):
            raise ApiError(403, "Forbidden", "forbidden")

    def status() -> dict[str, Any]:
        return {
            "pendingPairing": state.pending_guest is not None,
            "paired": state.paired_guest is not None,
            "chatDelayMs": state.chat_delay_ms,
            "ackDelayMs": state.ack_delay_ms,
            "nextChatFail": state.next_chat_fail,
            "nextAckLoss": state.next_ack_loss,
            "nextStaleVersion": state.next_stale_version,
            "nextCatalogMissing": state.next_catalog_missing,
            "nextShadeMissing": state.next_shade_missing,
            "fakeLlmCalls": state.model_calls,
        }

    @app.get("/__control")
    async def get_control(request: Request):
        admin(request)
        return status()

    @app.post("/__control")
    async def set_control(body: Control, request: Request):
        admin(request)
        if body.unpair:
            state.paired_guest = state.pending_guest = None
        if body.pair_pending:
            if state.pending_guest is None or state.paired_guest is not None:
                raise ApiError(409, "No pending guest to pair", "fake_pairing_unavailable")
            state.paired_guest, state.pending_guest = state.pending_guest, None
        for name in (
            "chat_delay_ms",
            "ack_delay_ms",
            "next_chat_fail",
            "next_ack_loss",
            "next_stale_version",
            "next_catalog_missing",
            "next_shade_missing",
        ):
            value = getattr(body, name)
            if value is not None:
                setattr(state, name, value)
        return status()

    return app


def is_private_lan(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
        return isinstance(ip, ipaddress.IPv4Address) and any(ip in net for net in _PRIVATE)
    except ValueError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated guest-only VISHUE fake AR server")
    parser.add_argument(
        "--bind", default="127.0.0.1", help="Loopback or one specific private PC IPv4"
    )
    parser.add_argument(
        "--device-ip", help="One allowed private device IPv4; required for LAN binding"
    )
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()
    if args.bind != "127.0.0.1" and (not is_private_lan(args.bind) or not args.device_ip):
        parser.error(
            "LAN requires a specific private --bind and --device-ip; wildcards are forbidden"
        )
    if args.device_ip and (not is_private_lan(args.device_ip) or args.bind == "127.0.0.1"):
        parser.error("--device-ip requires a private device IP and private LAN bind")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if get_settings().env.lower() not in {"local", "development", "dev", "test"}:
        parser.error("This test server requires a local or development ENV")
    secret = os.environ.get("VISHUE_FAKE_ADMIN", "")
    try:
        app = create_fake_app(secret, args.device_ip)
    except ValueError as exc:
        parser.error(str(exc))
    config = uvicorn.Config(
        app,
        host=args.bind,
        port=args.port,
        access_log=False,
        proxy_headers=False,
        log_level="critical",
        workers=1,
    )
    sockets: list[socket.socket] = []
    try:
        # A specific LAN bind does not include loopback; bind exactly these two addresses.
        for host in ("127.0.0.1", args.bind) if args.bind != "127.0.0.1" else ("127.0.0.1",):
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(server_socket)
            server_socket.bind((host, args.port))
            server_socket.listen(128)
            server_socket.setblocking(False)
        emit(
            "startup",
            mode="FAKE TEST ONLY",
            port=args.port,
            deviceRestricted=args.device_ip is not None,
        )
        uvicorn.Server(config).run(sockets=sockets)
    finally:
        for server_socket in sockets:
            server_socket.close()


if __name__ == "__main__":
    main()
