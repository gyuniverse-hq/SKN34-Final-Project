import json
import re
from typing import Protocol

from fastapi import Depends

from app.clients.llm_client import LlmClient, get_llm_client
from app.core.errors import ApiError, UpstreamError
from app.core.graph import get_driver
from app.repositories.graph_repository import GraphRepository
from app.schemas.chat import ChatRequest, ChatResponse, GraphProduct, ProductRef

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
    """Retrieves related products from the graph, then asks the LLM to answer with them only."""

    def __init__(self, graph: GraphReader, llm: Completer) -> None:
        self._graph = graph
        self._llm = llm

    async def answer(self, req: ChatRequest) -> ChatResponse:
        if not self._llm.configured:
            raise ApiError(503, "Chatbot is not configured", "chatbot_unavailable")
        products = await self._graph.find_products(extract_terms(req.message))
        try:
            answer = await self._llm.complete(build_messages(req, products))
        except UpstreamError as exc:
            raise ApiError(502, "Chatbot is temporarily unavailable", "upstream_error") from exc
        refs = [
            ProductRef(id=p.id, brand=p.brand, name=p.name, category=p.category) for p in products
        ]
        return ChatResponse(answer=answer, products=refs)


def get_chat_service(llm: LlmClient = Depends(get_llm_client)) -> ChatService:
    return ChatService(GraphRepository(get_driver()), llm)
