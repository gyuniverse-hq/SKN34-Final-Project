import logging
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, StrictBool, ValidationError

from app.core.errors import ApiError, UpstreamError
from app.schemas.catalog import BaseProductType
from app.schemas.chat import ChatRequest
from app.schemas.supervisor import IngredientPlanCondition, SearchPlan, SupervisorModel

logger = logging.getLogger(__name__)
PROMPT_VERSION = "g1-ko-v7"
SEARCH_TOOL = "catalog_search_products"
DETAIL_TOOL = "catalog_get_product_detail"
_PROVIDER_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_PRODUCT = re.compile(
    r"제품|상품|화장품|틴트|틴투|립|파운데이션|쿠션|블러셔|아이섀도|선크림|스킨케어"
)
_SEARCH_REQUEST = re.compile(
    r"추천\s*(?:해|부탁|[?!.]*$)|찾아\s*줘|보여\s*줘|검색해|골라\s*줘|살\s*만한"
)
_NO_SEARCH = re.compile(r"(?:추천|검색|조회)(?:은|는|을)?\s*(?:하지\s*마|말고|없이|빼|안)|설명만")

SYSTEM_PROMPT = """한국어로 K-뷰티 상담을 하세요. 간결하고 구체적인 팁을 주세요.
일반 설명이나 사용법 질문에는 상품을 조회하지 말고 답하세요. 애매하면 한 가지를 되물으세요.
실제 상품 추천·검색은 검색 도구를 사용하세요. 명확한 오타는 고쳐 이해하세요.
화면 상품의 색상·가격·성분은 상세 도구를 사용하세요. 화면의 상품 ID는 서버가 정합니다.
브랜드/제품명만 검색어에 넣으세요. 립 틴트처럼 일반 제품 유형은 category에 반영하세요.
현재가, 성분, 제형, 재고, 피부 안전, AR 적용 여부를 근거 없이 단정하지 마세요.
호수/옵션 검색, 성분 포함·제외 검색, 가격·제형·성분 복합 검색은 optionSearch=true로 검색하세요.
G4 옵션 검색에서 파운데이션이나 쿠션을 명시하면 category=base와 별도로 productType을 넣으세요.
파운데이션은 foundation, 쿠션은 cushion입니다. 상품명 검색어에 유형만 넣지 마세요.
ingredientConditions에 요청한 모든 성분과 includes/excludes를 보존하세요.
무향료는 fragranceFree이며 특정 성분 부재와 같지 않습니다.
향료 제외는 ingredientConditions의 향료/excludes이고 fragranceFree가 아닙니다.
3만원 이하는 maxPriceKRW=30000, 3만원 미만은 maxPriceKRW=29999입니다.
일반 추천·예산 상한은 VISHUE 등록 가격 기준 catalog_reference입니다.
명시적 판매처 현재가·실시간 가격은 current_offer, 옵션 수집가는 collected_snapshot입니다.
예산과 무향료를 함께 요청하면 optionSearch=true로 검색하세요.
추천 문장의 "지금 골라줘"는 일반 추천입니다. 판매처는 상품명 검색어에 넣지 마세요.
같은 예산으로 색상이 있는 상품을 찾으면 이전 가격 상한과 기준을 유지하세요.
특정 날짜·기간의 가격 검색은 지원하지 않습니다. 날짜 조건 원문을 unsupportedConditions에
반드시 보존하고 최신 수집가로 대체하지 마세요.
미지원 제형·재고·효능 등도 unsupportedConditions에 남기고 조건을 빼지 마세요.
보지 못한 얼굴을 봤다고 하거나 진단하거나 알레르기 위험이 없다고 말하지 마세요.
AR 적용과 장기 기억을 수행했다고 말하지 마세요.
"""


class CatalogSearchArgs(SupervisorModel):
    product_type: BaseProductType | None = None
    option_search: StrictBool = False
    price_basis: Literal["current_offer", "catalog_reference", "collected_snapshot"] | None = None
    texture: Literal["matte"] | None = None
    ingredient_conditions: list[IngredientPlanCondition] = Field(default_factory=list, max_length=6)
    unsupported_conditions: list[str] = Field(default_factory=list, max_length=8)
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


def _requires_catalog_search(message: str) -> bool:
    return bool(
        _PRODUCT.search(message)
        and _SEARCH_REQUEST.search(message)
        and not _NO_SEARCH.search(message)
    )


def requests_general_explanation(message: str) -> bool:
    return bool(
        re.search(
            r"차이|비교|어떻게\s*달라|뭐가\s*달라|설명|뭐야|무엇|사용법|어떻게\s*바르", message
        )
    )


async def explain_general_question(request: ChatRequest, llm) -> str:
    """Explain the general question without sending Catalog descriptions to the model."""
    try:
        answer = await llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "사용자의 질문에서 뷰티 개념이나 사용법만 한국어로 설명하세요. "
                        "브랜드, 상품명, 가격, 성분 검증이나 진단을 언급하지 마세요. "
                        "구매나 AR 실행도 언급하지 마세요. "
                        "상품 결과가 뒤따르므로 상품을 추천하지 않겠다는 말은 하지 마세요. "
                        "모르는 사실을 단정하지 말고 제품별 차이가 있으면 알려주세요."
                    ),
                },
                {"role": "user", "content": request.message},
            ]
        )
    except UpstreamError as exc:
        raise ApiError(502, "Chatbot is temporarily unavailable", "upstream_error") from exc
    if not isinstance(answer, str) or not answer.strip():
        raise ApiError(502, "Invalid G1 model explanation", "invalid_tool_result")
    return answer.strip()


async def choose_g1_turn(request: ChatRequest, complete_with_tools) -> G1ModelTurn:
    screen = request.screen_context
    tools = [_tool(SEARCH_TOOL, "카탈로그 상품 검색", CatalogSearchArgs)]
    if screen and screen.product_id:
        tools.append(_tool(DETAIL_TOOL, "현재 화면 상품의 색상·가격·성분 조회", CatalogDetailArgs))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": request.message},
    ]
    # A request about the displayed product may legitimately use the detail tool.
    screen_detail = bool(
        screen
        and screen.product_id
        and re.search(r"(?:이|현재|지금\s*보는|화면(?:의)?)\s*(?:상품|제품)", request.message)
        and not re.search(r"추천|검색|찾아|다른|비슷한|대신", request.message)
    )
    required_search = _requires_catalog_search(request.message) and not screen_detail
    # Offer search only for an actual search request; a vague or no-recommendation
    # question must not let the model turn general advice into a Catalog lookup.
    if not (_SEARCH_REQUEST.search(request.message) and not _NO_SEARCH.search(request.message)):
        tools = [tool for tool in tools if tool["function"]["name"] == DETAIL_TOOL]
    try:
        result, duration = await complete_with_tools(messages, tools)
        choice = result["choices"][0]
        if (
            required_search
            and choice["finish_reason"] == "stop"
            and not choice["message"].get("tool_calls")
        ):
            logger.info("g1_catalog_tool_retry", extra={"reason": "required_search_missing"})
            result, duration = await complete_with_tools(messages, tools, required_tool=SEARCH_TOOL)
    except UpstreamError as exc:
        raise ApiError(502, "Chatbot is temporarily unavailable", "upstream_error") from exc
    except (AttributeError, IndexError, KeyError, TypeError) as exc:
        raise ApiError(502, "Invalid G1 model response", "invalid_tool_result") from exc

    try:
        choice = result["choices"][0]
        message = choice["message"]
        calls = message.get("tool_calls") or []
        rejected_call_id = None
        if not calls and choice["finish_reason"] == "stop":
            if required_search:
                raise ValueError("The requested product search requires a Catalog tool call")
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
            if name not in {tool["function"]["name"] for tool in tools}:
                raise ValueError("Unavailable G1 tool")
            if required_search and name != SEARCH_TOOL:
                raise ValueError("Expected the Catalog search tool")
            if name == SEARCH_TOOL:
                search = CatalogSearchArgs.model_validate_json(args)
                if not search.category and not (search.query or "").strip():
                    rejected_call_id = call_id
                    turn = G1ModelTurn(
                        SearchPlan(intent="general"),
                        "확인하지 않은 현재 판매가와 성분은 확정할 수 없어요. "
                        "카탈로그에서 참고 가격과 확인 가능한 상품 정보를 살펴볼 수 있어요. "
                        "어떤 종류의 제품을 찾으시나요?",
                    )
                else:
                    plan = SearchPlan(intent="search", **search.model_dump())
                    turn = G1ModelTurn(plan, tool_call_id=call_id, tool_name=name)
            elif name == DETAIL_TOOL and screen and screen.product_id:
                detail = CatalogDetailArgs.model_validate_json(args)
                plan = SearchPlan(intent=detail.intent)
                turn = G1ModelTurn(plan, tool_call_id=call_id, tool_name=name)
            else:
                raise ValueError("Unavailable G1 tool")
        model_id, response_id = result["model"], result["id"]
        usage = result.get("usage") or {}
        if not all(
            isinstance(v, str) and _PROVIDER_ID.fullmatch(v) for v in (model_id, response_id)
        ):
            raise ValueError("Missing completion identity")
        token_counts = [usage.get(key) for key in ("prompt_tokens", "completion_tokens")]
    except (AttributeError, IndexError, KeyError, TypeError, ValidationError, ValueError) as exc:
        raise ApiError(502, "Invalid G1 model response", "invalid_tool_result") from exc

    if rejected_call_id:
        logger.info(
            "g1_model_tool_rejected",
            extra={
                "tool_call_id": rejected_call_id,
                "tool_name": SEARCH_TOOL,
                "reason": "unbounded_catalog_search",
            },
        )
    logger.info(
        "g1_model_completion",
        extra={
            "model_id": model_id,
            "model_response_id": response_id,
            "prompt_version": PROMPT_VERSION,
            "request_type": request.request_type,
            "input_tokens": token_counts[0] if type(token_counts[0]) is int else None,
            "output_tokens": token_counts[1] if type(token_counts[1]) is int else None,
            "duration_ms": duration,
            "tool_call_id": turn.tool_call_id,
            "tool_name": turn.tool_name,
        },
    )
    return turn
