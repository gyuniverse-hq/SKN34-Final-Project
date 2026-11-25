"""Admin Ops summary service unit checks (no live chatbot)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.services.admin_ops_service import AdminOpsService


@pytest.mark.anyio
async def test_chatbot_reports_unconfigured_without_base_url(tmp_path: Path):
    settings = Settings(
        admin_enabled=True,
        admin_lip_eval_dir=tmp_path,
        chatbot_base_url=None,
    )
    service = AdminOpsService(MagicMock(), settings)
    result = await service.chatbot()
    assert result["configured"] is False
    assert result["error"]


@pytest.mark.anyio
async def test_system_reports_lip_dir_and_admin_flag(tmp_path: Path):
    settings = Settings(
        env="local",
        admin_enabled=True,
        admin_lip_eval_dir=tmp_path,
        cors_origins=["http://127.0.0.1:5173"],
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value="0036")))
    service = AdminOpsService(session, settings)
    result = await service.system()
    assert result["adminEnabled"] is True
    assert result["alembicHead"] == "0036"
    assert result["lipEvalDirExists"] is True
    assert result["corsOriginCount"] == 1
