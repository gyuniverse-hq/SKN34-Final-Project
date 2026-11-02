import json
import re
from hashlib import sha256
from typing import Protocol

from fastapi import Depends

from app.clients.catalog_client import CatalogClient, get_catalog_client
from app.clients.llm_client import LlmClient, get_llm_client
from app.core.config import get_settings
from app.core.errors import ApiError, UpstreamError
from app.core.graph import get_driver
from app.repositories.ar_command_repository import MemoryArRequestRepository, get_ar_requests
from app.repositories.graph_repository import GraphRepository
from app.schemas.chat import ArAckRequest, ChatRequest, ChatResponse, GraphProduct, ProductRef
from app.services.ar_command_service import propose_ar_command

LANGUAGE = {"en": "English", "ko": "Korean", "ja": "Japanese", "zh": "Simplified Chinese"}
MAX_TERMS = 8
_WORD = re.compile(r"[\w가-힣ぁ-んァ-ン一-龥]{2,}")

SYSTEM_PROMPT = """You are VISHUE's K-beauty shopping assistant for international visitors.
Answer in {language}, in at most 5 short sentences.
Recommend only products from the PRODUCTS list below, by brand and name. If none fit, say so.
Never ask for, describe, or comment on photos or video of the user's face.
PRODUCTS (JSON): {products}"""


class GraphReader(Protocol):
    async def find_products(self, terms: list[str], limit: int = 6) -> list[GraphProduct]: ...


class Completer(Protocol):
    @property
    def configured(self) -> bool: ...
    async def complete(self, messages: list[dict[str, str]]) -> str: ...


def extract_terms(message: str) -> list[str]:
    seen: dict[str, None] = {}
    for word in _WORD.findall(message.lower()):
        seen.setdefault(word, None)
    return list(seen)[:MAX_TERMS]


def build_messages(req: ChatRequest, products: list[GraphProduct]) -> list[dict[str, str]]:
    context = json.dumps(
        [p.model_dump(mode="json", exclude_none=True) for p in products], ensure_ascii=False
    )
    system = SYSTEM_PROMPT.format(language=LANGUAGE[req.locale], products=context)
    if req.skin and (req.skin.mst or req.skin.undertone):
        system += (
            f"\nUser skin tone (on-device estimate): Monk scale {req.skin.mst or 'unknown'},"
            f" undertone {req.skin.undertone or 'unknown'}."
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": req.message}]


class ChatService:
    """Retrieves product candidates and asks the LLM to answer the user's question."""

    def __init__(
        self, graph: GraphReader | None, llm: Completer, catalog=None, requests=None
    ) -> None:
        self._graph = graph
        self._llm = llm
        self._catalog = catalog
        self._requests = requests

    async def answer(self, req: ChatRequest, principal_key: str | None = None) -> ChatResponse:
        if req.request_type == "ar_command":
            if get_settings().is_production:
                raise ApiError(
                    503, "AR request storage is not configured", "ar_requests_unavailable"
                )
            if not principal_key or self._requests is None or req.request_id is None:
                raise ApiError(503, "AR request storage is unavailable", "ar_requests_unavailable")
            fingerprint = sha256(req.model_dump_json().encode("utf-8")).hexdigest()
            return await self._requests.run(
                principal_key, req.request_id, fingerprint, lambda: self._propose_ar(req)
            )
        if not self._llm.configured:
            raise ApiError(503, "Chatbot is not configured", "chatbot_unavailable")
        graph = self._graph if self._graph is not None else GraphRepository(get_driver())
        products = await graph.find_products(extract_terms(req.message))
        try:
            answer = await self._llm.complete(build_messages(req, products))
        except UpstreamError as exc:
            raise ApiError(502, "Chatbot is temporarily unavailable", "upstream_error") from exc
        refs = [
            ProductRef(id=p.id, brand=p.brand, name=p.name, category=p.category) for p in products
        ]
        return ChatResponse(answer=answer, products=refs)

    async def _propose_ar(self, req: ChatRequest) -> ChatResponse:
        result = await propose_ar_command(req, self._llm)
        proposal = result.ar_result.action_proposal if result.ar_result else None
        if proposal is None:
            return result
        try:
            product = await self._catalog.get_product(proposal.product_id)
        except UpstreamError as exc:
            raise ApiError(502, "Catalog is temporarily unavailable", "upstream_error") from exc
        if (
            product is None
            or product.id != proposal.product_id
            or product.makeup_zone != "lip"
            or not any(shade.id == proposal.shade_id for shade in product.shades)
        ):
            raise ApiError(422, "Invalid lip product or shade", "invalid_ar_selection")
        return result

    def acknowledge_ar(self, principal_key: str, ack: ArAckRequest) -> None:
        if get_settings().is_production or self._requests is None:
            raise ApiError(503, "AR request storage is unavailable", "ar_requests_unavailable")
        self._requests.record_ack(principal_key, ack)


def get_chat_service(
    llm: LlmClient = Depends(get_llm_client),
    catalog: CatalogClient = Depends(get_catalog_client),
    requests: MemoryArRequestRepository = Depends(get_ar_requests),
) -> ChatService:
    return ChatService(None, llm, catalog, requests)
