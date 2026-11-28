"""API-produced test response replayed through the real CatalogClient and N02.

Catalog data/review/transport are synthetic. No live model or PostgreSQL claim.
"""

import json
import os
import xml.etree.ElementTree as ET

import httpx
import pytest

from app.clients.catalog_client import CatalogClient
from app.core.config import get_settings
from app.services.chat_service import ChatService
from tests.conftest import FakeLlm
from tests.test_g8_owned_look import product, request


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_api_recipe_reaches_n02_exact_product_and_parent(monkeypatch, record_property):
    path = os.environ.get("G8_RECIPE_API_JUNIT")
    if not path:
        pytest.skip("API recipe_delivery_payload JUnit required")
    properties = ET.parse(path).findall(".//property[@name='recipe_delivery_payload']")
    assert len(properties) == 1
    payload = json.loads(properties[0].attrib["value"])
    calls = []

    def handle(req):
        calls.append(str(req.url))
        if req.url.path == "/api/style-looks":
            return httpx.Response(200, json=payload)
        row = product("blush-b", "blush").model_dump(mode="json", by_alias=True)
        if req.url.path == "/api/products/blush-b":
            return httpx.Response(200, json={"product": row})
        if req.url.path == "/api/products":
            return httpx.Response(200, json={"products": [row]})
        raise AssertionError(f"Unexpected Catalog request: {req.url.path}")

    monkeypatch.setattr(get_settings(), "g8_enabled", True)
    req = request([], "블러셔는 없어.")
    req.style_context.kind = "video"
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    catalog = CatalogClient("http://catalog.test")
    response = await ChatService(None, FakeLlm(configured=False), catalog).answer(req)
    assert response.style_recipe.basis == "reviewed_recipe"
    assert response.style_recipe.evidence_id == "fixture:evidence"
    usage = response.style_recipe.products[0].product_usages[0]
    assert usage.evidence_id == "fixture:usage" and usage.step_order == 1
    assert usage.shade_id == "blush-b-shade"
    assert [p.id for p in response.products] == ["blush-b"]
    assert response._consultation_parent.tasks[0].goal == "owned_look"
    record_property(
        "recipe_delivery_evidence",
        json.dumps(
            {
                "dataMode": "mock",
                "transportMode": "mock",
                "modelMode": "not_used",
                "externalModelCalls": 0,
                "requests": calls,
                "response": response.model_dump(mode="json", by_alias=True),
                "tasks": response._parent_trace,
            },
            ensure_ascii=False,
        ),
    )
