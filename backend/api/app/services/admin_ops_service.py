"""Read-only admin Ops summaries (recommendations, chatbot probe, system)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from fastapi import Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.models.cart_recommendation import CartRecommendationVisitRow
from app.models.recommendation_feedback import (
    RecommendationImpressionRow,
    SkincareRecommendationEventRow,
)


class AdminOpsService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings

    async def recommendations(self) -> dict:
        impressions = await self.session.scalar(
            select(func.count()).select_from(RecommendationImpressionRow)
        )
        skincare_events = await self.session.scalar(
            select(func.count()).select_from(SkincareRecommendationEventRow)
        )
        cart_visits = await self.session.scalar(
            select(func.count()).select_from(CartRecommendationVisitRow)
        )
        return {
            "arPaletteMode": self.settings.ar_palette_mode,
            "arPaletteExperiment": self.settings.ar_palette_experiment or None,
            "cartRecommendationExperiment": self.settings.cart_recommendation_experiment or None,
            "counts": {
                "recommendationImpressions": int(impressions or 0),
                "skincareEvents": int(skincare_events or 0),
                "cartRecommendationVisits": int(cart_visits or 0),
            },
        }

    async def chatbot(self) -> dict:
        base = (self.settings.chatbot_base_url or "").rstrip("/")
        if not base:
            return {
                "configured": False,
                "baseUrl": None,
                "healthz": None,
                "readyz": None,
                "error": "CHATBOT_BASE_URL is not set",
            }
        healthz = await self._probe(f"{base}/healthz")
        readyz = await self._probe(f"{base}/readyz")
        return {
            "configured": True,
            "baseUrl": base,
            "healthz": healthz,
            "readyz": readyz,
            "error": None,
        }

    async def system(self) -> dict:
        lip = Path(self.settings.admin_lip_eval_dir)
        version = None
        try:
            version = (
                await self.session.execute(text("select version_num from alembic_version"))
            ).scalar()
        except Exception:
            version = None
        lip_exists = await asyncio.to_thread(lip.is_dir)
        return {
            "env": self.settings.env,
            "adminEnabled": self.settings.admin_enabled,
            "alembicHead": version,
            "lipEvalDir": str(lip),
            "lipEvalDirExists": lip_exists,
            "llmConfigured": bool(
                self.settings.llm_api_key and (self.settings.llm_model or self.settings.astra_model)
            ),
            "chatbotBaseUrl": self.settings.chatbot_base_url,
            "corsOriginCount": len(self.settings.cors_origins),
        }

    async def _probe(self, url: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url)
            body: object
            try:
                body = response.json()
            except Exception:
                body = {"raw": response.text[:200]}
            return {"ok": response.is_success, "status": response.status_code, "body": body}
        except Exception as exc:
            return {"ok": False, "status": None, "body": {"error": str(exc)[:200]}}


def get_admin_ops_service(
    session: AsyncSession = Depends(get_session),
) -> AdminOpsService:
    return AdminOpsService(session, get_settings())
