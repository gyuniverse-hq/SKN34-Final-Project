"""Real loopback HTTP between services, SYNTHETIC SQL and LLM; no real DB or LLM API."""

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from app.core.cache import NullCache
from app.core.config import get_settings
from app.repositories.ingredient_repository import IngredientRepository
from app.schemas.catalog import CatalogBundle
from app.services.catalog_service import CatalogService, get_catalog_service
from app.services.ingredient_service import IngredientService, get_ingredient_service
from tests.conftest import FakeCatalogStore, make_product
from tests.test_ingredient_api import Session
from tests.test_ingredient_api import data as data
from tests.test_ingredient_canonical_identity import row

CHAT_SCRIPT = r"""
import json, sys, time
from fastapi.testclient import TestClient
from app.main import create_app
from app.clients.catalog_client import CatalogClient
from app.services.chat_service import ChatService, get_chat_service

class Llm:
    configured = True
    calls = 0
    async def complete(self, messages):
        self.calls += 1
        return json.dumps({"intent":"detail", "ingredientLookup":True,
                           "ingredientName":sys.argv[2]})

class Service(ChatService):
    result = None
    async def answer(self, *args, **kwargs):
        self.result = await super().answer(*args, **kwargs)
        return self.result

llm = Llm()
service = Service(None, llm, CatalogClient(sys.argv[1]))
app = create_app()
app.dependency_overrides[get_chat_service] = lambda: service
with TestClient(app) as client:
    response = client.post('/api/chat', json={
        "message":"이 상품의 Water 성분은?", "locale":"ko", "requestType":"beauty_consultation",
        "chatContext": {"issuedAt":int(time.time()), "filters":{},
            "candidateIds":["oy-fixture"], "selectedProductId":"oy-fixture",
            "shadeSelections":{"oy-fixture":"01-2"}}
    }, headers={"X-Vishue-Anonymous-Id":"guest-session-0123456789-abcdefghijk"})
    result = service.result
    print(json.dumps({"httpStatus":response.status_code, "body":response.json(),
        "toolStatus":result.supervisor.result.status if result else None,
        "application":result.supervisor.result.application if result else None,
        "llmCalls":llm.calls}))
"""


@pytest.mark.parametrize(
    "state,verdict,status",
    [
        ("verified", "MATCH", "success"),
        ("canonical_alias", "MATCH", "success"),
        ("candidate", "UNKNOWN", "clarification"),
        ("configuration_error", "ERROR", "error"),
        ("approval_missing", "ERROR", "error"),
        ("approval_damaged", "ERROR", "error"),
    ],
)
def test_api_client_beauty_supervisor_chat_json_over_http(
    client,
    data,
    tmp_path,
    monkeypatch,
    state,
    verdict,
    status,
):
    chatbot = Path(__file__).resolve().parents[2] / "chatbot"
    python = chatbot / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if configured_python := os.environ.get("VISHUE_CHATBOT_TEST_PYTHON"):
        python = Path(configured_python)
    if not python.exists():
        pytest.skip("Existing chatbot virtualenv is required; no dependency installation")
    product, shades, raw, entries, mapping = data
    if state == "candidate":
        mapping.mapping_status = "candidate"
        mapping.review_status = "unreviewed"
        mapping.ingredient_coverage = "unknown"
        # Emulate the current collected-candidate metadata; rows are still test doubles.
        mapping.synthetic = False
    path = tmp_path / "runtime-mapping.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "records": [mapping.model_dump(mode="json", by_alias=True)],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("INGREDIENT_MAPPING_PATH", raising=False)
    sessions = []
    monkeypatch.setattr(get_settings(), "skincare_refresh_enabled", False)
    invalid_approval = state.startswith("approval_")
    approval_path = tmp_path / "approval.csv"
    if state == "approval_damaged":
        approval_path.write_bytes(
            b'mfds_ingredient_id,candidate_alias,source_hash,reviewed_by,reviewed_at\n1,"unclosed'
        )
    monkeypatch.setattr(
        get_settings(),
        "ingredient_alias_approvals_path",
        str(approval_path) if invalid_approval else None,
    )

    def ingredient_service():
        identity_pages = (
            [
                [row(1, oy=1), row(2, oy=2)],
                [
                    (1, "standard-1", "english-1", "Aqua"),
                    (2, "standard-2", "english-2", "alias-2"),
                ],
                [(*row(1, oy=1)[:10], "Aqua", False, False, True)],
            ]
            if state == "canonical_alias"
            else [[], []]
        )
        session = Session([[product], shades, [raw], entries, *identity_pages])
        sessions.append(session)
        return IngredientService(
            IngredientRepository(
                session,
                mapping_path=None if state == "configuration_error" else path,
            )
        )

    bundle = CatalogBundle(
        products=[make_product("oy-fixture", "lip", shades)], looks=[], stores=[]
    )
    catalog_service = CatalogService(FakeCatalogStore(bundle), NullCache(), 60)
    client.app.dependency_overrides[get_catalog_service] = lambda: catalog_service
    client.app.dependency_overrides[get_ingredient_service] = ingredient_service
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(client.app, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                threading.Event().wait(0.01)
            assert server.started, "Synthetic Catalog HTTP server did not start"
            if invalid_approval:
                base = f"http://127.0.0.1:{port}"
                with httpx.Client(base_url=base) as http:
                    response = http.get(
                        "/api/products/oy-fixture/ingredients", params={"shadeId": "01-2"}
                    )
                    assert response.status_code == 503
                    assert response.json()["code"] == "ingredient_alias_approvals_invalid"
                    assert http.get("/api/products").status_code == 200
            result = subprocess.run(
                [
                    str(python),
                    "-B",
                    "-c",
                    CHAT_SCRIPT,
                    f"http://127.0.0.1:{port}",
                    "Aqua" if state == "canonical_alias" else "Water",
                ],
                cwd=chatbot,
                env=os.environ | {"ENV": "local", "LLM_API_KEY": ""},
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=25,
                check=True,
            )
        finally:
            server.should_exit = True
            thread.join(timeout=5)
        assert not thread.is_alive()
    output = json.loads(result.stdout.strip().splitlines()[-1])
    assert output["httpStatus"] == 200 and output["llmCalls"] == 1
    assert output["toolStatus"] == status and output["application"] == "not_requested"
    body = output["body"]
    assert body["ingredientResults"][0]["verdict"] == verdict
    assert body["ingredientResults"][0]["productId"] == body["products"][0]["id"]
    assert "supervisor" not in body and "toolResult" not in body and "arResult" not in body
    expected_queries = 7 if state == "canonical_alias" else 6 if state == "verified" else 2
    if invalid_approval:
        assert sessions and all(not session.statements for session in sessions)
        assert body["ingredientResults"][0]["reason"] == "source_unavailable"
    else:
        assert sessions and len(sessions[0].statements) == expected_queries
