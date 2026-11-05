import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Raised anywhere below the routers; rendered as the app's `ApiErrorBody` ({error, code})."""

    def __init__(self, status: int, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


class UpstreamError(Exception):
    """An external dependency (LLM, catalog API) failed or answered unexpectedly."""


def error_body(message: str, code: str | None) -> dict[str, str]:
    return {"error": message, "code": code} if code else {"error": message}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.message, exc.code), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(error_body("Invalid request", "invalid_request"), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else None
        return JSONResponse(error_body(str(exc.detail), code), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error")
        return JSONResponse(error_body("Internal server error", "internal"), status_code=500)
