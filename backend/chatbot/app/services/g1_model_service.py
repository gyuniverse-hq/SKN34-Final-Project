import logging
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, StrictBool, ValidationError

from app.core.errors import ApiError, UpstreamError
from app.schemas.chat import ChatRequest
from app.schemas.supervisor import SearchPlan, SupervisorModel

logger = logging.getLogger(__name__)
PROMPT_VERSION = "g1-ko-v1"
SEARCH_TOOL = "catalog_search_products"
DETAIL_TOOL = "catalog_get_product_detail"
_PROVIDER_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")

SYSTEM_PROMPT = """한국어로 K-뷰티 상담을 하세요. 간결하고 구체적인 팁을 주세요.
일반 설명이나 사용법 질문에는 상품을 조회하지 말고 답하세요. 애매하면 한 가지를 되물으세요.
실제 상품 추천·검색은 검색 도구를 사용하세요. 명확한 오타는 고쳐 이해하세요.
화면 상품의 색상·가격·성분은 상세 도구를 사용하세요. 화면의 상품 ID는 서버가 정합니다.
브랜드/제품명만 검색어에 넣으세요. 립 틴트처럼 일반 제품 유형은 category에 반영하세요.
현재가, 성분, 제형, 재고, 피부 안전, AR 적용 여부를 근거 없이 단정하지 마세요.
보지 못한 얼굴을 봤다고 하거나 진단하거나 알레르기 위험이 없다고 말하지 마세요.
AR 적용과 장기 기억을 수행했다고 말하지 마세요.
"""


class CatalogSearchArgs(SupervisorModel):
    category: Literal["lip", "cheek", "eye", "base", "skincare", "suncare"] | None = None
    query: str | None = Field(default=None, max_length=80)
    max_price_krw: int | None = Field(default=None, alias="maxPriceKRW", ge=0, strict=True)
    moisturizing: StrictBool | None = None
    fragrance_free: StrictBool | None = None


class CatalogDetailArgs(SupervisorModel):
    intent: Literal["detail", "price"] = "detail"


def _tool(name, description, args):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": args.model_json_schema(),
        },
    }


@dataclass(frozen=True)
class G1ModelTurn:
    plan: SearchPlan
    answer: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None


async def choose_g1_turn(request: ChatRequest, complete_with_tools) -> G1ModelTurn:
    screen = request.screen_context
    tools = [_tool(SEARCH_TOOL, "카탈로그 상품 검색", CatalogSearchArgs)]
    if screen and screen.product_id:
        tools.append(_tool(DETAIL_TOOL, "현재 화면 상품의 색상·가격·성분 조회", CatalogDetailArgs))
    try:
        result, duration = await complete_with_tools(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": request.message},
            ],
            tools,
        )
    except UpstreamError as exc:
        raise ApiError(502, "Chatbot is temporarily unavailable", "upstream_error") from exc

    try:
        choice = result["choices"][0]
        message = choice["message"]
        calls = message.get("tool_calls") or []
        if not calls and choice["finish_reason"] == "stop":
            answer = message["content"].strip()
            if not answer:
                raise ValueError("Empty G1 answer")
            turn = G1ModelTurn(SearchPlan(intent="general"), answer)
        else:
            if len(calls) != 1 or choice["finish_reason"] != "tool_calls":
                raise ValueError("Expected one G1 tool call")
            call = calls[0]
            call_id, name = call["id"], call["function"]["name"]
            if (
                call["type"] != "function"
                or not isinstance(call_id, str)
                or not _PROVIDER_ID.fullmatch(call_id)
            ):
                raise ValueError("Invalid G1 tool call")
            args = call["function"]["arguments"]
            if name == SEARCH_TOOL:
                search = CatalogSearchArgs.model_validate_json(args)
                if not search.category and not (search.query or "").strip():
                    raise ValueError("Unbounded catalog search")
                plan = SearchPlan(intent="search", **search.model_dump())
            elif name == DETAIL_TOOL and screen and screen.product_id:
                detail = CatalogDetailArgs.model_validate_json(args)
                plan = SearchPlan(intent=detail.intent)
            else:
                raise ValueError("Unavailable G1 tool")
            turn = G1ModelTurn(plan, tool_call_id=call_id, tool_name=name)
        model_id, response_id = result["model"], result["id"]
        usage = result.get("usage") or {}
        if not all(
            isinstance(v, str) and _PROVIDER_ID.fullmatch(v) for v in (model_id, response_id)
        ):
            raise ValueError("Missing completion identity")
        token_counts = [usage.get(key) for key in ("prompt_tokens", "completion_tokens")]
    except (AttributeError, IndexError, KeyError, TypeError, ValidationError, ValueError) as exc:
        raise ApiError(502, "Invalid G1 model response", "invalid_tool_result") from exc

    logger.info(
        "g1_model_completion",
        extra={
            "model_id": model_id,
            "model_response_id": response_id,
            "prompt_version": PROMPT_VERSION,
            "input_tokens": token_counts[0] if type(token_counts[0]) is int else None,
            "output_tokens": token_counts[1] if type(token_counts[1]) is int else None,
            "duration_ms": duration,
            "tool_call_id": turn.tool_call_id,
            "tool_name": turn.tool_name,
        },
    )
    return turn
