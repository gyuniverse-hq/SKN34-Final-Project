"""Lip product-panel eval: refs save + AR score aggregation."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import anyio
import pytest
from PIL import Image

from app.core.errors import ApiError
from app.services.lip_eval_catalog import LIP_EVAL_PRODUCTS
from app.services.lip_eval_panel_service import LipEvalPanelService


class _Upload:
    def __init__(self, data: bytes, filename: str, content_type: str):
        self._data = data
        self.filename = filename
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._data


def _png(color: tuple[int, int, int]) -> bytes:
    from io import BytesIO

    buf = BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, format="PNG")
    return buf.getvalue()


def _make_service(root: Path):
    slots: dict[tuple[str, int], object] = {}
    products = [
        type(
            "P",
            (),
            {
                "id": p["id"],
                "brand": p["brand"],
                "name": p["name"],
                "shade": p["shade"],
                "sort_order": p["sortOrder"],
            },
        )()
        for p in LIP_EVAL_PRODUCTS
    ]

    class FakeRepo:
        async def products(self):
            return products

        async def product(self, product_id):
            return next((p for p in products if p.id == product_id), None)

        async def slots_for(self, product_id):
            return [s for (pid, _), s in slots.items() if pid == product_id]

        async def all_slots(self):
            return list(slots.values())

        async def slot(self, product_id, rater_id):
            return slots.get((product_id, rater_id))

        async def upsert_slot(self, row):
            slots[(row.product_id, row.rater_id)] = row
            return row

        def audit(self, *args, **kwargs):
            return None

        def transaction(self):
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def _tx():
                yield

            return _tx()

    vision = AsyncMock()
    vision.score_naturalness = AsyncMock(
        return_value={
            "criteriaVersion": "naturalness-techlang-v1.1",
            "scores": {"delta_e": 4, "ssim": 4, "mae": 4, "miou": 3, "lpips": 4},
            "mean": 3.8,
            "briefReason": "ok",
            "model": "test",
        }
    )
    service = LipEvalPanelService(FakeRepo(), vision, root)  # type: ignore[arg-type]
    return service, vision, slots


def test_save_refs_then_score_ar():
    root = Path(__file__).resolve().parent / "_lip_eval_tmp"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    try:
        service, vision, slots = _make_service(root)
        pid = LIP_EVAL_PRODUCTS[0]["id"]
        bare = _Upload(_png((180, 120, 120)), "bare.png", "image/png")
        real = _Upload(_png((200, 80, 100)), "real.png", "image/png")
        ar = _Upload(_png((198, 82, 102)), "ar.png", "image/png")

        after_refs = anyio.run(service.save_refs, pid, 1, bare, real, "actor")
        slot = next(s for s in after_refs["slots"] if s["raterId"] == 1)
        assert slot["readyForAr"] is True
        assert slot["scored"] is False

        after_ar = anyio.run(service.score_ar, pid, 1, ar, "actor")
        slot = next(s for s in after_ar["slots"] if s["raterId"] == 1)
        assert slot["scored"] is True
        assert after_ar["aggregate"]["scoredCount"] == 1
        assert after_ar["aggregate"]["finalized"] is False
        assert after_ar["aggregate"]["naturalnessMean"] == 3.8
        vision.score_naturalness.assert_awaited()
        assert (service.root / slots[(pid, 1)].bare_path).is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_score_ar_requires_refs():
    root = Path(__file__).resolve().parent / "_lip_eval_tmp2"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    try:
        service, _, _ = _make_service(root)
        pid = LIP_EVAL_PRODUCTS[0]["id"]
        ar = _Upload(_png((198, 82, 102)), "ar.png", "image/png")
        with pytest.raises(ApiError) as exc:
            anyio.run(service.score_ar, pid, 1, ar, "actor")
        assert exc.value.code == "invalid_request"
    finally:
        shutil.rmtree(root, ignore_errors=True)
