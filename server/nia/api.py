"""Authenticated desktop image inference. Run one Uvicorn worker, without reload."""

import asyncio
import io
import logging
import os
import time
import tomllib
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import torch
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from ml.src.skin_analysis.runtime import select_cuda

from .auth import AuthUnavailable, SupabaseTokenVerifier, TestTokenVerifier
from .engine import sha256
from .face_detection import DEFAULT_MODEL, YuNetRegions
from .imaging import MAX_PIXELS
from .recommendation import RecommendationAnalyzer

ROOT = Path(__file__).absolute().parents[2]
LOGGER = logging.getLogger(__name__)
BEARER = HTTPBearer(auto_error=False)
MIME_TYPES = {"image/jpeg", "image/png"}


@dataclass(frozen=True)
class Settings:
    supabase_url: str = ""
    supabase_publishable_key: str = field(default="", repr=False)
    gpu_uuid: str = ""
    auth_mode: str = "supabase"
    test_bearer_token: str = field(default="", repr=False)
    bundle: Path = ROOT / "ml/runs/skin-analysis-v2"
    face_model: Path = DEFAULT_MODEL
    max_upload_bytes: int = 12 * 1024 * 1024

    def __post_init__(self):
        from urllib.parse import urlsplit

        if self.auth_mode == "supabase":
            origin = urlsplit(self.supabase_url)
            if (
                origin.scheme != "https"
                or not origin.hostname
                or origin.username
                or origin.password
                or origin.query
                or origin.fragment
                or origin.path not in ("", "/")
            ):
                raise ValueError("SUPABASE_URL must be the project's HTTPS origin")
            if not self.supabase_publishable_key.strip():
                raise ValueError("SUPABASE_PUBLISHABLE_KEY is required")
        elif self.auth_mode == "test-token":
            if len(self.test_bearer_token.encode("utf-8")) < 32:
                raise ValueError("SKIN_TEST_BEARER_TOKEN must contain at least 32 bytes")
        else:
            raise ValueError("SKIN_AUTH_MODE must be 'supabase' or 'test-token'")
        if not self.gpu_uuid.startswith("GPU-"):
            raise ValueError("SKIN_GPU_UUID must be an NVIDIA GPU UUID")
        if not 1024 <= self.max_upload_bytes <= 32 * 1024 * 1024:
            raise ValueError("SKIN_MAX_UPLOAD_BYTES must be between 1024 and 33554432")

    @classmethod
    def from_env(cls):
        with (ROOT / "ml/configs/resnet50_multilabel.toml").open("rb") as handle:
            default_gpu = tomllib.load(handle)["train"]["device_uuid"]
        return cls(
            supabase_url=os.environ.get("SUPABASE_URL", ""),
            supabase_publishable_key=os.environ.get("SUPABASE_PUBLISHABLE_KEY", ""),
            gpu_uuid=os.environ.get("SKIN_GPU_UUID", default_gpu),
            auth_mode=os.environ.get("SKIN_AUTH_MODE", "supabase"),
            test_bearer_token=os.environ.get("SKIN_TEST_BEARER_TOKEN", ""),
            bundle=Path(os.environ.get("SKIN_MODEL_BUNDLE", ROOT / "ml/runs/skin-analysis-v2")),
            face_model=Path(os.environ.get("SKIN_FACE_MODEL", DEFAULT_MODEL)),
            max_upload_bytes=int(os.environ.get("SKIN_MAX_UPLOAD_BYTES", str(12 * 1024 * 1024))),
        )


@dataclass
class GpuRuntime:
    analyzer: RecommendationAnalyzer
    gpu: str
    bundle_version: str = ""

    def analyze(self, raw):
        started = time.perf_counter()
        # Verify the encoded format and pixel budget before OpenCV allocates a decoded image.
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ("JPEG", "PNG"):
                raise ValueError("Only JPEG/PNG up to 30 megapixels are supported")
            if image.width * image.height > MAX_PIXELS:
                raise ValueError("Only JPEG/PNG up to 30 megapixels are supported")
            image.verify()
        result = self.analyzer.analyze(raw)
        return {
            **result,
            "execution": {
                "runtime": "pytorch-cuda",
                "bundleVersion": self.bundle_version,
                "serverMs": (time.perf_counter() - started) * 1000,
            },
        }

    def close(self):
        for engine in self.analyzer.engines.values():
            engine.model = None
        self.analyzer.acne.model = None
        self.analyzer.acne.bundle = None
        torch.cuda.empty_cache()


def load_runtime(settings):
    """Fail startup instead of silently falling back to CPU or lazy request loading."""
    device = select_cuda(settings.gpu_uuid)
    torch.cuda.set_device(device)
    os.environ["NIA_EVAL_DEVICE"] = str(device)
    regions = YuNetRegions(settings.face_model)
    analyzer = RecommendationAnalyzer(settings.bundle, region_locator=regions)
    engines = [*analyzer.engines.values(), analyzer.acne]
    for engine in engines:
        engine.load()
        devices = {tensor.device for tensor in engine.model.state_dict().values()}
        if devices != {device} or engine.model.training:
            raise RuntimeError("All four models must be in eval mode on the selected CUDA device")
    with torch.inference_mode():
        sample = torch.zeros(1, 3, 256, 256, device=device)
        for _ in range(3):
            analyzer.acne.model(sample)
    torch.cuda.synchronize(device)
    return GpuRuntime(
        analyzer, torch.cuda.get_device_name(device), sha256(settings.bundle / "manifest.json")
    )


def error(status, code, message, *, headers=None):
    return HTTPException(status, detail={"error": message, "code": code}, headers=headers)


async def image_bytes(request, limit):
    """Bound the entire upload, then parse one multipart file entirely in RAM."""
    mime = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if mime not in MIME_TYPES | {"multipart/form-data"}:
        raise error(415, "UNSUPPORTED_IMAGE", "Send a JPEG/PNG file as multipart field 'file'.")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            declared = int(length)
        except ValueError as exc:
            raise error(400, "INVALID_UPLOAD", "Invalid Content-Length.") from exc
        if declared < 0:
            raise error(400, "INVALID_UPLOAD", "Invalid Content-Length.")
        if declared > limit:
            raise error(413, "IMAGE_TOO_LARGE", "The upload exceeds the configured size limit.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise error(413, "IMAGE_TOO_LARGE", "The upload exceeds the configured size limit.")
        body.extend(chunk)
    if mime in MIME_TYPES:
        raw = bytes(body)
    else:

        async def chunks():
            yield bytes(body)

        parser = MultiPartParser(request.headers, chunks(), max_files=1, max_fields=0)
        # Starlette otherwise spools camera JPEGs larger than 1 MiB to disk.
        # The whole body has already been bounded below this per-parser threshold.
        parser.spool_max_size = limit + 1
        try:
            form = await parser.parse()
        except (MultiPartException, ValueError) as exc:
            raise error(400, "INVALID_UPLOAD", "Expected one multipart JPEG/PNG file.") from exc
        try:
            items = form.multi_items()
            if len(items) != 1 or items[0][0] != "file" or not isinstance(items[0][1], UploadFile):
                raise error(422, "INVALID_UPLOAD", "Expected exactly one file in field 'file'.")
            upload = items[0][1]
            if upload.content_type not in MIME_TYPES:
                raise error(415, "UNSUPPORTED_IMAGE", "Only JPEG/PNG uploads are supported.")
            raw = await upload.read()
        finally:
            await form.close()
    if not raw:
        raise error(422, "INVALID_IMAGE", "The image is empty.")
    return raw


def create_app(
    settings=None, *, runtime_factory=load_runtime, verifier_factory=SupabaseTokenVerifier
):
    @asynccontextmanager
    async def lifespan(app):
        active = settings if settings is not None else Settings.from_env()
        if active.auth_mode == "test-token":
            app.state.verifier = TestTokenVerifier(active.test_bearer_token)
        else:
            app.state.verifier = verifier_factory(active.supabase_url, active.supabase_publishable_key)
        runtime = await run_in_threadpool(runtime_factory, active)
        app.state.settings = active
        app.state.runtime = runtime
        app.state.analysis_lock = asyncio.Lock()
        try:
            yield
        finally:
            await run_in_threadpool(runtime.close)
            del app.state.runtime

    app = FastAPI(
        title="Desktop skin inference",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    async def authenticate(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(BEARER)],
    ):
        claims = None
        if credentials is not None and credentials.scheme.lower() == "bearer":
            try:
                claims = await request.app.state.verifier.verify(credentials.credentials)
            except AuthUnavailable as exc:
                raise error(
                    503, "AUTH_UNAVAILABLE", "Authentication is temporarily unavailable."
                ) from exc
        if claims is None:
            raise error(
                401,
                "UNAUTHORIZED",
                "Provide a valid inference access token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return claims

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        content = (
            exc.detail
            if isinstance(exc.detail, dict)
            else {
                "error": "The request could not be handled.",
                "code": "REQUEST_ERROR",
            }
        )
        return JSONResponse(content, status_code=exc.status_code, headers=exc.headers)

    @app.middleware("http")
    async def no_store(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health", dependencies=[Depends(authenticate)])
    async def health(request: Request):
        return {
            "status": "ready",
            "device": "cuda:0",
            "gpu": request.app.state.runtime.gpu,
            "models_loaded": 4,
        }

    @app.post("/analyze", dependencies=[Depends(authenticate)])
    async def analyze(request: Request):
        lock = request.app.state.analysis_lock
        if lock.locked():
            raise error(
                503,
                "SERVER_BUSY",
                "An analysis is already running. Retry shortly.",
                headers={"Retry-After": "1"},
            )
        async with lock:
            raw = await image_bytes(request, request.app.state.settings.max_upload_bytes)
            try:
                result = await run_in_threadpool(request.app.state.runtime.analyze, raw)
            except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
                raise error(422, "INVALID_IMAGE", "The JPEG/PNG could not be decoded.") from exc
            except ValueError as exc:
                message = str(exc)
                if message.startswith("No frontal face detected"):
                    raise error(422, "FACE_NOT_FOUND", message) from exc
                if message.startswith("Multiple faces detected"):
                    raise error(422, "MULTIPLE_FACES", message) from exc
                if message.startswith("Face is too close"):
                    raise error(422, "FACE_OUT_OF_BOUNDS", message) from exc
                raise error(
                    422, "INVALID_IMAGE", "A valid JPEG/PNG up to 30MP is required."
                ) from exc
            except Exception as exc:
                LOGGER.exception("Skin inference failed")
                raise error(
                    500, "INFERENCE_FAILED", "Skin inference could not be completed."
                ) from exc
            # Keep the existing complete/partial feature schema, with no image previews.
            if result.get("acne", {}).get("status") == "failed":
                result["acne"]["error"] = "Acne inference could not be completed."
            return JSONResponse(result)

    return app


app = create_app()
