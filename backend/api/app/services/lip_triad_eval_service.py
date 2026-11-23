"""Admin lip triad scoring: technical numbers + Astra naturalness. Images are not stored."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.vision_llm_client import VisionLlmClient, get_vision_llm_client
from app.core.db import get_session
from app.core.errors import ApiError
from app.core.observability import request_id_var
from app.repositories.admin_repository import AdminRepository
from app.services.lip_technical_metrics import MAX_BYTES, score_triad

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}


def _mime(content_type: str | None, filename: str | None) -> str:
    raw = (content_type or "").split(";")[0].strip().lower()
    if raw in ALLOWED_MIME:
        return raw
    name = (filename or "").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".webp"):
        return "image/webp"
    if name.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    raise ApiError(400, "Only JPEG, PNG, or WebP images are allowed", "invalid_request")


async def _read_image(upload) -> tuple[bytes, str]:
    if upload is None:
        raise ApiError(400, "bare, real, and ar images are required", "invalid_request")
    data = await upload.read()
    if not data:
        raise ApiError(400, "empty image upload", "invalid_request")
    if len(data) > MAX_BYTES:
        raise ApiError(400, "image too large (max 8MB)", "invalid_request")
    return data, _mime(upload.content_type, upload.filename)


class LipTriadEvalService:
    def __init__(self, repo: AdminRepository, vision: VisionLlmClient):
        self.repo = repo
        self.vision = vision

    async def evaluate(self, bare, real, ar, actor: str) -> dict:
        bare_bytes, bare_mime = await _read_image(bare)
        real_bytes, real_mime = await _read_image(real)
        ar_bytes, ar_mime = await _read_image(ar)
        try:
            technical = score_triad(bare_bytes, real_bytes, ar_bytes)
        except ValueError as exc:
            raise ApiError(400, str(exc), "invalid_request") from exc

        naturalness = await self.vision.score_naturalness(
            real_bytes,
            ar_bytes,
            real_mime=real_mime,
            ar_mime=ar_mime,
            bare_bytes=bare_bytes,
            bare_mime=bare_mime,
        )

        run_id = str(uuid4())
        digest = hashlib.sha256(
            bare_bytes + b"|" + real_bytes + b"|" + ar_bytes
        ).hexdigest()[:16]
        # Scores only — never image bytes, paths, or filenames.
        after = {
            "technicalOverall": technical["overall"],
            "naturalnessMean": naturalness["mean"],
            "technicalVersion": technical["criteriaVersion"],
            "naturalnessVersion": naturalness["criteriaVersion"],
            "contentDigest16": digest,
        }
        async with self.repo.transaction():
            self.repo.audit(
                actor,
                "lip_triad_eval",
                "lip_triad",
                run_id,
                None,
                after,
                request_id_var.get() or "unknown",
            )
        return {
            "id": run_id,
            "technical": technical,
            "naturalness": naturalness,
            "retainedImages": False,
        }


def get_lip_triad_eval_service(
    session: AsyncSession = Depends(get_session),
    vision: VisionLlmClient = Depends(get_vision_llm_client),
) -> LipTriadEvalService:
    return LipTriadEvalService(AdminRepository(session), vision)
