"""Product-panel lip eval: store bare/real refs, score AR per rater, average by product."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.vision_llm_client import VisionLlmClient, get_vision_llm_client
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.core.observability import request_id_var
from app.models.admin import LipEvalSlotRow
from app.repositories.lip_eval_repository import LipEvalRepository
from app.services.lip_eval_catalog import LIP_EVAL_RATERS, PRODUCT_IDS, RATER_IDS
from app.services.lip_technical_metrics import MAX_BYTES, score_triad
from app.services.lip_triad_eval_service import ALLOWED_MIME, _mime

IMAGE_KINDS = frozenset({"bare", "real", "ar"})


def _ext(mime: str) -> str:
    return {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[mime]


async def _read_upload(upload: UploadFile | None, *, required: bool) -> tuple[bytes, str] | None:
    if upload is None:
        if required:
            raise ApiError(400, "image upload is required", "invalid_request")
        return None
    data = await upload.read()
    if not data:
        raise ApiError(400, "empty image upload", "invalid_request")
    if len(data) > MAX_BYTES:
        raise ApiError(400, "image too large (max 8MB)", "invalid_request")
    mime = _mime(upload.content_type, upload.filename)
    if mime not in ALLOWED_MIME:
        raise ApiError(400, "Only JPEG, PNG, or WebP images are allowed", "invalid_request")
    return data, mime


class LipEvalPanelService:
    def __init__(self, repo: LipEvalRepository, vision: VisionLlmClient, root: Path):
        self.repo = repo
        self.vision = vision
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _write(self, product_id: str, rater_id: int, kind: str, data: bytes, mime: str) -> str:
        rel = f"{product_id}/rater-{rater_id}/{kind}{_ext(mime)}"
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return rel.replace("\\", "/")

    def _abs(self, rel: str | None) -> Path | None:
        if not rel:
            return None
        path = (self.root / rel).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ApiError(400, "invalid image path", "invalid_request")
        return path

    def _slot_view(self, slot: LipEvalSlotRow | None, rater_id: int, product_id: str) -> dict:
        rater = next(r for r in LIP_EVAL_RATERS if r["id"] == rater_id)
        has_bare = bool(slot and slot.bare_path)
        has_real = bool(slot and slot.real_path)
        has_ar = bool(slot and slot.ar_path)
        scored = bool(slot and slot.technical_json and slot.naturalness_json)
        return {
            "raterId": rater_id,
            "label": rater["label"],
            "hasBare": has_bare,
            "hasReal": has_real,
            "hasAr": has_ar,
            "readyForAr": has_bare and has_real,
            "scored": scored,
            "technical": slot.technical_json if slot else None,
            "naturalness": slot.naturalness_json if slot else None,
            "scoredAt": slot.scored_at.isoformat() if slot and slot.scored_at else None,
            "imageUrls": {
                "bare": f"/api/admin/lip-eval/products/{product_id}/raters/{rater_id}/images/bare"
                if has_bare
                else None,
                "real": f"/api/admin/lip-eval/products/{product_id}/raters/{rater_id}/images/real"
                if has_real
                else None,
                "ar": f"/api/admin/lip-eval/products/{product_id}/raters/{rater_id}/images/ar"
                if has_ar
                else None,
            },
        }

    def _aggregate(self, slots: list[dict]) -> dict:
        scored = [s for s in slots if s["scored"] and s["naturalness"]]
        n = len(scored)
        if n == 0:
            return {
                "scoredCount": 0,
                "finalized": False,
                "naturalnessMean": None,
                "technicalOverallPassRate": None,
                "metricMeans": None,
            }
        nat_mean = sum(float(s["naturalness"]["mean"]) for s in scored) / n
        pass_n = sum(
            1 for s in scored if s["technical"] and s["technical"].get("overall") == "pass"
        )
        metric_means: dict[str, float] = {}
        keys = ("delta_e", "ssim", "mae", "miou", "lpips")
        for key in keys:
            vals = []
            for s in scored:
                item = (s["technical"] or {}).get("items", {}).get(key) or {}
                if item.get("value") is not None:
                    vals.append(float(item["value"]))
                score = (s["naturalness"] or {}).get("scores", {}).get(key)
                if score is not None:
                    metric_means.setdefault(f"naturalness_{key}", [])
                    metric_means[f"naturalness_{key}"].append(float(score))
            if vals:
                metric_means[key] = sum(vals) / len(vals)
        for key, vals in list(metric_means.items()):
            if isinstance(vals, list):
                metric_means[key] = sum(vals) / len(vals)
        return {
            "scoredCount": n,
            "finalized": n == 5,
            "naturalnessMean": round(nat_mean, 2),
            "technicalOverallPassRate": round(pass_n / n, 2),
            "metricMeans": metric_means,
        }

    async def list_products(self) -> dict:
        products = await self.repo.products()
        all_slots = await self.repo.all_slots()
        by_product: dict[str, list[LipEvalSlotRow]] = {}
        for slot in all_slots:
            by_product.setdefault(slot.product_id, []).append(slot)
        items = []
        for product in products:
            slot_map = {s.rater_id: s for s in by_product.get(product.id, [])}
            views = [
                self._slot_view(slot_map.get(r["id"]), r["id"], product.id) for r in LIP_EVAL_RATERS
            ]
            items.append(
                {
                    "id": product.id,
                    "brand": product.brand,
                    "name": product.name,
                    "shade": product.shade,
                    "sortOrder": product.sort_order,
                    "aggregate": self._aggregate(views),
                    "slots": views,
                }
            )
        return {"items": items, "raters": LIP_EVAL_RATERS}

    async def get_product(self, product_id: str) -> dict:
        if product_id not in PRODUCT_IDS:
            raise ApiError(404, "product not found", "not_found")
        product = await self.repo.product(product_id)
        if product is None:
            raise ApiError(404, "product not found", "not_found")
        slot_map = {s.rater_id: s for s in await self.repo.slots_for(product_id)}
        views = [
            self._slot_view(slot_map.get(r["id"]), r["id"], product_id) for r in LIP_EVAL_RATERS
        ]
        return {
            "id": product.id,
            "brand": product.brand,
            "name": product.name,
            "shade": product.shade,
            "sortOrder": product.sort_order,
            "aggregate": self._aggregate(views),
            "slots": views,
            "raters": LIP_EVAL_RATERS,
        }

    async def save_refs(
        self, product_id: str, rater_id: int, bare: UploadFile, real: UploadFile, actor: str
    ) -> dict:
        self._validate_ids(product_id, rater_id)
        bare_up = await _read_upload(bare, required=True)
        real_up = await _read_upload(real, required=True)
        assert bare_up and real_up
        bare_bytes, bare_mime = bare_up
        real_bytes, real_mime = real_up
        bare_rel = self._write(product_id, rater_id, "bare", bare_bytes, bare_mime)
        real_rel = self._write(product_id, rater_id, "real", real_bytes, real_mime)
        slot = await self.repo.slot(product_id, rater_id)
        before = {
            "hasBare": bool(slot and slot.bare_path),
            "hasReal": bool(slot and slot.real_path),
        }
        if slot is None:
            slot = LipEvalSlotRow(product_id=product_id, rater_id=rater_id)
        slot.bare_path = bare_rel
        slot.real_path = real_rel
        # Changing refs invalidates prior AR score for this slot.
        slot.ar_path = None
        slot.technical_json = None
        slot.naturalness_json = None
        slot.scored_at = None
        async with self.repo.transaction():
            await self.repo.upsert_slot(slot)
            self.repo.audit(
                actor,
                "lip_eval_refs_saved",
                f"{product_id}:{rater_id}",
                before,
                {"hasBare": True, "hasReal": True},
                request_id_var.get() or "unknown",
            )
        return await self.get_product(product_id)

    async def score_ar(self, product_id: str, rater_id: int, ar: UploadFile, actor: str) -> dict:
        self._validate_ids(product_id, rater_id)
        slot = await self.repo.slot(product_id, rater_id)
        if slot is None or not slot.bare_path or not slot.real_path:
            raise ApiError(400, "bare and real images must be saved first", "invalid_request")
        bare_path = self._abs(slot.bare_path)
        real_path = self._abs(slot.real_path)
        if (
            bare_path is None
            or real_path is None
            or not bare_path.is_file()
            or not real_path.is_file()
        ):
            raise ApiError(400, "stored bare/real images are missing", "invalid_request")
        ar_up = await _read_upload(ar, required=True)
        assert ar_up
        ar_bytes, ar_mime = ar_up
        bare_bytes = bare_path.read_bytes()
        real_bytes = real_path.read_bytes()
        bare_mime = {
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(bare_path.suffix.lower(), "image/jpeg")
        real_mime = {
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(real_path.suffix.lower(), "image/jpeg")
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
        ar_rel = self._write(product_id, rater_id, "ar", ar_bytes, ar_mime)
        from datetime import UTC, datetime

        slot.ar_path = ar_rel
        slot.technical_json = technical
        slot.naturalness_json = naturalness
        slot.scored_at = datetime.now(UTC)
        async with self.repo.transaction():
            await self.repo.upsert_slot(slot)
            self.repo.audit(
                actor,
                "lip_eval_ar_scored",
                f"{product_id}:{rater_id}",
                None,
                {
                    "technicalOverall": technical.get("overall"),
                    "naturalnessMean": naturalness.get("mean"),
                },
                request_id_var.get() or "unknown",
            )
        detail = await self.get_product(product_id)
        detail["lastScore"] = {
            "raterId": rater_id,
            "technical": technical,
            "naturalness": naturalness,
            "retainedImages": True,
        }
        return detail

    async def read_image(self, product_id: str, rater_id: int, kind: str) -> tuple[bytes, str]:
        self._validate_ids(product_id, rater_id)
        if kind not in IMAGE_KINDS:
            raise ApiError(404, "image kind not found", "not_found")
        slot = await self.repo.slot(product_id, rater_id)
        rel = None if slot is None else getattr(slot, f"{kind}_path")
        path = self._abs(rel)
        if path is None or not path.is_file():
            raise ApiError(404, "image not found", "not_found")
        suffix = path.suffix.lower()
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")
        return path.read_bytes(), mime

    def _validate_ids(self, product_id: str, rater_id: int) -> None:
        if product_id not in PRODUCT_IDS:
            raise ApiError(404, "product not found", "not_found")
        if rater_id not in RATER_IDS:
            raise ApiError(404, "rater not found", "not_found")


def get_lip_eval_panel_service(
    session: AsyncSession = Depends(get_session),
    vision: VisionLlmClient = Depends(get_vision_llm_client),
) -> LipEvalPanelService:
    settings = get_settings()
    return LipEvalPanelService(
        LipEvalRepository(session), vision, Path(settings.admin_lip_eval_dir)
    )
