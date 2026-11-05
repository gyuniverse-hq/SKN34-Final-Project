import json
import logging
import time
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_RESERVED = set(vars(logging.makeLogRecord({})))


class JsonFormatter(logging.Formatter):
    """One JSON object per line so cluster log collectors can index fields."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        payload.update({k: v for k, v in vars(record).items() if k not in _RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(service: str, level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True


class RequestContextMiddleware:
    """Propagates X-Request-ID, logs one access line per request, and defaults Cache-Control."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger("access")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        request_id = headers.get(b"x-request-id", b"").decode()[:64] or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                out = list(message.get("headers", []))
                out.append((b"x-request-id", request_id.encode()))
                if not any(name.lower() == b"cache-control" for name, _ in out):
                    out.append((b"cache-control", b"no-store"))
                message["headers"] = out
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope["path"]
            if not path.startswith(("/healthz", "/readyz")):
                self.logger.info(
                    "request",
                    extra={
                        "method": scope["method"],
                        "path": path,
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )
            request_id_var.reset(token)
