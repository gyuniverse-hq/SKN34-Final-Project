import json
import logging
import re
import secrets
import time
import unicodedata
from functools import partial
from hashlib import sha256
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import Depends

from app.clients.catalog_client import CatalogClient, get_catalog_client
from app.clients.llm_client import LlmClient, get_llm_client
from app.core.config import get_settings
from app.core.errors import ApiError, UpstreamError
from app.core.graph import get_driver
from app.core.observability import catalog_tool_call_id
from app.repositories.ar_command_repository import MemoryArRequestRepository, get_ar_requests
from app.repositories.chat_session_repository import ChatSessionRepository, get_chat_sessions
from app.repositories.graph_repository import GraphRepository
from app.schemas.chat import (
    ArAckRequest,
    BeautyContext,
    BeautyFilters,
    ChatRequest,
    ChatResponse,
    ChatSessionRef,
    ChatSessionState,
    GraphProduct,
    IngredientFilter,
    PendingClarification,
    ProductRef,
)
from app.schemas.supervisor import (
    ConditionCheck,
    EvidenceRef,
    IngredientPlanCondition,
    IntentDecision,
    ResolvedContext,
    SearchPlan,
    Sufficiency,
    SupervisorResult,
    TaskPlan,
    ToolResult,
)
from app.schemas.vishue_state import VishueState
from app.services.ar_command_service import propose_ar_command
from app.services.beauty_consultation_service import (
    COMPARISON_SCREENS,
    TEXT,
    _resolve_product_reference,
    _shade_label,
    abandons_ingredient_goal,
    direct_comparison,
    execute_beauty,
    interpret_beauty,
    refers_to_same_budget,
)
from app.services.g1_catalog_tool import G1CatalogTool
from app.services.g1_model_service import (
    DETAIL_TOOL,
    G1ModelTurn,
    _requires_catalog_search,
    choose_g1_turn,
    explain_general_question,
    requests_general_explanation,
)
from app.services.knowledge_service import consult_knowledge
from app.services.product_consultation_graph import SupervisorRuntime, product_supervisor
from app.services.style_recipe_service import TEXT as STYLE_TEXT
from app.services.style_recipe_service import execute_style

LANGUAGE = {"en": "English", "ko": "Korean", "ja": "Japanese", "zh": "Simplified Chinese"}
MAX_TERMS = 8
logger = logging.getLogger(__name__)
_WORD = re.compile(r"[\w가-힣ぁ-んァ-ン一-龥]{2,}")

# Route explicit G2 filter requests through the richer interpreter, not G1's first-search args.
_G2_FILTER = re.compile(r"매트|matte|제형|지속력|워터프루프|waterproof|글로시|벨벳|새틴", re.I)
_FILTER_CHANGE = re.compile(r"바꿔|바꾸|변경|조건|추천|찾아|골라|유지|빼|제외|말고")


def _g5_enabled() -> bool:
    return bool(getattr(get_settings(), "g5_enabled", False))


def _cancels_pending(message: str) -> bool:
    # Honor the last correction; a negated cancellation is not a cancellation.
    commands = list(
        re.finditer(
            r"(?:취소|그만)(?:(\s*(?:하지\s*(?:말고|말아|마|않\w*)|(?:는\s*)?안\s*\w*|말고))"
            r"|\s*(?:해(?:줘|주세요|요)?|하자|할게|할래|하고|해주세요)|(?=$|[.!?,。！？]))",
            message,
        )
    )
    return not bool(commands[-1].group(1)) if commands else bool(re.search(r"질문.*됐어", message))


def _unsupported_g2_change(message: str, slots: SearchPlan) -> bool:
    if slots.unsupported_conditions:
        return True
    changing = slots.intent in {"search", "refine"} or bool(_FILTER_CHANGE.search(message))
    if changing and re.search(
        r"지속력|워터프루프|waterproof|글로시|벨벳|새틴|더\s*매트", message, re.I
    ):
        return True
    if changing and re.search(r"매트|matte|제형", message, re.I):
        if "texture" in slots.clear_filters and slots.texture is None:
            return False
        if slots.texture != "matte" or re.search(r"매트\s*(?:말고|아닌|제외)", message):
            return True
    # A refine with no representable change must not renew the result and claim a match.
    if re.search(r"다시\s*(?:추천|검색|찾아)", message):
        return False
    return slots.intent == "refine" and not (
        slots.clear_filters
        or any(
            value is not None
            for value in (
                slots.category,
                slots.max_price_krw,
                slots.price_basis,
                slots.fragrance_free,
                slots.moisturizing,
                slots.texture,
                slots.query,
            )
        )
        or slots.ingredient_conditions
        or slots.ingredient_name
        or refers_to_same_budget(message)
    )


SYSTEM_PROMPT = """You are VISHUE's K-beauty shopping assistant for international visitors.
Answer in {language}, in at most 5 short sentences.
Answer the user's question directly. For general makeup or ingredient questions, do not mention
product availability unless the user also asks for product recommendations.
When recommending products, use only products from the PRODUCTS list below, by brand and name.
If the user asks for product recommendations and none of the listed products fit, say so.
Ingredient lists are partial key ingredients, not verified full ingredients. An absent fragrance
entry never proves fragrance-free status. Never invent catalog shades or ingredient coverage.
Never claim to execute AR changes or complete an app action.
Never present general style advice as a verified catalog recipe.
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


def resolve_context(req: ChatRequest) -> ResolvedContext:
    beauty, ar = req.chat_context, req.ar_context
    lip = ar.lip if ar else None
    return ResolvedContext(
        style=req.style_context,
        message=req.message,
        request_type=req.request_type,
        screen=req.screen_context,
        candidate_ids=list(beauty.candidate_ids) if beauty else [],
        selected_product_id=lip.product_id
        if lip
        else (beauty.selected_product_id if beauty else None),
        selected_shade_id=lip.shade_id if lip else None,
        ar_state_version=ar.state_version if ar else None,
        has_beauty_context=beauty is not None,
        has_ar_context=ar is not None,
    )


_SHOPPING = re.compile(r"추천|구매|recommend|buy|おすすめ|推荐|购买", re.I)
_LOOK_REFERENCE = re.compile(
    r"이\s*(?:룩|스타일)|\bthis (?:look|style)\b|このルック|这个妆容", re.I
)
_PRODUCT_FACT = re.compile(
    r"가격|얼마|성분|향료|비교|price|ingredient|fragrance|compare|価格|成分|比較|价格|香料|对比",
    re.I,
)
_KNOWLEDGE_TOPIC = re.compile(
    r"화장(?!실)|메이크업|색조|스킨케어|파운데이션|파데|쿠션|컨실러|코렉터|보정제|"
    r"\b립|틴트|파우더|블러셔|볼터치|[쉐셰]이?딩|마스카라|아이라이너|아이라인|섀도|"
    r"클렌징|폼\s*클렌저|세안제|선크림|자외선\s*차단|미백|발색|퍼프|스펀지|세럼|로션|에센스|"
    r"(?:눈가|피부)\s*젤|(?i:bb|cc)\s*크림|톤\s*업\s*크림|모공\s*프라이머|볼\s*색|"
    r"(?<![가-힣])(?:이마|코|광대|턱|볼|눈두덩)(?:에|는|쪽|의|위)?(?=[\s,.!?])"
    r"[^.!?]{0,15}하이라이트|토너[^.!?]{0,22}화장솜|"
    r"베이스(?=[^.!?]{0,24}(?:바르|바른|바를|펴|들뜨|밀리))"
)
_FACE_COVER = re.compile(
    r"(?:얼굴|볼|피부|실핏줄|흉터|여드름|백반증|홍조|다크\s*서클).*?(?:가리|가릴|커버|보정)"
)
_SOURCE_QUESTION = re.compile(r"연구|논문|설문|실험|시험|조사|자료|원문|시연|사례")
_KNOWLEDGE_FOLLOWUP = re.compile(
    r"^(?:그럼|그러면)(?:\s|[,，])|(?:^|\s)그\s+(?:논문|연구|자료|지표|방법|조건|부위|제품)"
    r"|(?:^|\s)(?:앞서|아까)\s*(?:말|언급|질문|본|보던)"
)
_PROTECTED_KNOWLEDGE_REQUEST = re.compile(
    r"가격|할인|최저가|재고|장바구니|전성분|성분표|배합표|제조번호|제조사|모델명|"
    r"색\s*번호|호수|옵션|매출|결제|영수증|진단|치료|처방|"
    r"(?:성분|향료).{0,14}(?:들어\s*있|함유|포함\s*여부)"
)
_CURRENT_PRODUCT_CONTEXT = re.compile(
    r"현재|지금|요즘|요새|온라인몰|쇼핑몰|판매|납품|유통|매장|시판|출고|올라온"
)
_PRODUCT_IDENTITY_QUESTION = re.compile(
    r"(?:같은|동일한?)\s*(?:제품|상품|물건)(?!\s*(?:종류|유형|처럼))"
    r"|(?:제품|상품|물건)(?:이|과|이랑|하고)?\s*(?:같은|동일)"
    r"|(?:그|해당)\s*(?:제품|상품|물건)(?:이|과|이랑|하고)?\s*맞"
)
_GENERAL_INGREDIENT_QUESTION = re.compile(r"일반적|종류|원리|역할")
_UNMEASURED_VALUE = re.compile(r"실측값|(?:촬영|측정)[^.!?]{0,22}(?:없|안\s*했)")
_SHOPPING_ZONES = {
    "lip": r"립|입술 제품|lip(?:stick| product| tint)?|リップ|唇",
    "eye": r"아이라이너|아이섀도|마스카라|eyeliner|eyeshadow|mascara|アイシャドウ|眼影|眼线",
    "cheek": r"블러셔|볼터치|blush|チーク|腮红",
    "base": r"파운데이션|쿠션|foundation|ファンデ|粉底",
}


def look_shopping_category(message):
    if not _SHOPPING.search(message) or re.search(
        r"브러시|면봉|도구|brush|tool|綿棒|刷子|工具", message, re.I
    ):
        return None
    return next(
        (zone for zone, pattern in _SHOPPING_ZONES.items() if re.search(pattern, message, re.I)),
        None,
    )


def _look_search_followup(message: str) -> bool:
    # A price constraint can refine the previous search without a recommendation verb.
    upper_limit = re.search(
        r"\d[\d,만천백십\s]*(?:원|krw|won|ウォン|韩元)\s*(?:이하|미만|以下|以内)"
        r"|\b(?:under|at most|up to)\s*(?:(?:₩|krw\s*)\d[\d,]*|\d[\d,]*\s*(?:krw|won)\b)",
        message,
        re.I,
    )
    price_change = (
        re.search(r"\d", message)
        and re.search(
            r"원|이하|미만|예산|krw|won|under|budget|ウォン|以下|以内|预算|韩元", message, re.I
        )
        and re.search(
            r"바꿔|변경|낮춰|올려|맞춰|change|lower|raise|set|変更|変えて|改成|换成", message, re.I
        )
    )
    return bool(
        (upper_limit and not message.rstrip().endswith(("?", "？")))
        or price_change
        or (
            _SHOPPING.search(message)
            and re.search(
                r"다시|그중|아까|\bagain\b|\bfrom those\b|もう一度|もう一回|再推荐|重新推荐",
                message,
                re.I,
            )
        )
    )


def _grounded_look_query(message, look_title, query):
    if not query or not query.strip():
        return None

    def normalized(text):
        return " ".join(unicodedata.normalize("NFKC", text).casefold().split())

    text, title, name = map(normalized, (message, look_title, query))
    text = re.sub(
        r"(?:룩|스타일)(?:의)?\s*(?:이름|제목)[이가은는]?\s+.+?(?:인데|이고|이라고|[,.!?])",
        " ",
        text,
    )
    if title:
        text = text.replace(title, " ")
    return query.strip() if name in text else None


def route_intent(context: ResolvedContext) -> IntentDecision:
    """Conservative routing hints; dedicated AR parsing still validates execution intent."""
    text = context.message.casefold()
    shopping = _SHOPPING.search(text)
    execution = re.search(r"발라|적용해|설정해|조절해|apply|set .*intensity|塗って|涂上", text)
    intent = "general"
    if shopping and execution:
        intent = "compound"
    elif context.request_type == "ar_command":
        intent = "ar"
    elif context.style is not None and (
        look_shopping_category(text) or (context.has_beauty_context and _look_search_followup(text))
    ):
        intent = "product"
    elif context.request_type in {"beauty_consultation", "style_consultation"} and (
        (context.screen and context.screen.screen_id in COMPARISON_SCREENS)
        or (
            _PRODUCT_FACT.search(text)
            and (
                context.style is not None
                or (context.screen and context.screen.product_id)
                or context.selected_product_id
            )
        )
    ):
        intent = (
            "ingredient"
            if re.search(r"성분|향료|ingredient|fragrance|成分|香料", text)
            or (context.screen and context.screen.screen_id == "product-ingredient-comparison")
            else "product"
        )
    elif (
        context.request_type == "style_consultation"
        or context.style is not None
        or _LOOK_REFERENCE.search(text)
        or (
            context.request_type != "beauty_consultation"
            and re.search(r"레시피|스타일|이 룩|이 스타일|recipe|style|レシピ|妆容", text)
        )
    ):
        intent = "style"
    elif re.search(r"성분|ingredient|成分", text):
        intent = "ingredient"
    elif context.request_type == "beauty_consultation":
        intent = "product"
    return IntentDecision(intent=intent, request_type_hint=context.request_type)


def _prior_knowledge_context(req: ChatRequest) -> str:
    if not _KNOWLEDGE_FOLLOWUP.search(req.message.strip()):
        return ""
    followups = []
    for turn in reversed(req.recent_messages):
        if turn.role != "user":
            continue
        text = turn.text.strip()
        if (
            _SHOPPING.search(text)
            or _requires_catalog_search(text)
            or _PROTECTED_KNOWLEDGE_REQUEST.search(text)
            or _LOOK_REFERENCE.search(text)
        ):
            return ""
        # A follow-up mentioning a tool still needs its original topic and conditions.
        if _KNOWLEDGE_FOLLOWUP.search(text):
            followups.append(text)
            continue
        topic = _KNOWLEDGE_TOPIC.search(text) or _FACE_COVER.search(text)
        if topic or re.search(r"젤\s*크림", text):
            return "\n".join([text, *reversed(followups)])
        return ""
    return ""


def _is_knowledge_question(
    req: ChatRequest, context: ResolvedContext, decision: IntentDecision
) -> bool:
    # Keep selection capabilities and pending replies on the existing session path.
    if (
        req.locale != "ko"
        or context.style is not None
        or context.has_beauty_context
        or req.clarification_id is not None
        or (
            context.screen
            and (
                context.screen.product_id
                or context.screen.look_id
                or context.screen.style_id
                or context.screen.screen_id in COMPARISON_SCREENS
            )
        )
    ):
        return False

    free_chat = req.request_type == "chat" and decision.intent in {"general", "ingredient"}
    app_makeup = (
        req.request_type == "beauty_consultation"
        and req.general_makeup
        and context.screen is None
        and decision.intent in {"product", "ingredient"}
    )
    if not (free_chat or app_makeup):
        return False

    message = context.message
    prior = _prior_knowledge_context(req)
    source_question = bool(_SOURCE_QUESTION.search(message))
    explains = requests_general_explanation(message)
    if (
        _SHOPPING.search(message)
        or _requires_catalog_search(message)
        or _PROTECTED_KNOWLEDGE_REQUEST.search(message)
        or (
            source_question
            and _CURRENT_PRODUCT_CONTEXT.search(message)
            and _PRODUCT_IDENTITY_QUESTION.search(message)
        )
    ):
        return False
    if not source_question:
        if _UNMEASURED_VALUE.search(message):
            return False
        if decision.intent == "ingredient" and not (
            explains and _GENERAL_INGREDIENT_QUESTION.search(message)
        ):
            return False

    return bool(
        (_KNOWLEDGE_TOPIC.search(message) or _FACE_COVER.search(message) or prior)
        and (
            source_question
            or _SOURCE_QUESTION.search(prior)
            or req.general_makeup
            or explains
            or re.search(
                r"[?？]|어떻|어디|어느|어떤|뭘|방법|주의|좋을까요|되나요|할까요|"
                r"잡아\s*줘(?:요)?[.!]?$|(?:인지|는지)\s*(?:궁금해|헷갈려)",
                message,
            )
        )
    )


def check_sufficiency(context: ResolvedContext, intent: IntentDecision) -> Sufficiency:
    # Missing AR slots are clarified by the existing AR Tool (same localized reasons).
    missing = []
    if intent.intent == "style" and context.style is None:
        missing.append("styleContext")
    if intent.intent == "ar":
        if not context.has_ar_context:
            missing.append("arContext")
        if not context.selected_product_id or not context.selected_shade_id:
            missing.append("lipSelection")
    if (
        intent.slots
        and not context.has_beauty_context
        and (
            intent.slots.intent in {"detail", "price", "refine"} or intent.slots.scope == "previous"
        )
    ):
        missing.append("chatContext")
    return Sufficiency(ready=not missing, missing=missing)


def build_plan(
    context: ResolvedContext, intent: IntentDecision, sufficiency: Sufficiency
) -> TaskPlan:
    if intent.intent == "knowledge":
        return TaskPlan(tasks=["knowledge"])
    if intent.intent == "compound":
        return TaskPlan(stop_reason="compound_request_unsupported")
    if intent.intent == "ar":
        return TaskPlan(tasks=["ar_command"], stop_reason=None)
    if intent.intent == "style":
        return TaskPlan(
            tasks=["style"], stop_reason="clarify_in_tool" if not sufficiency.ready else None
        )
    if intent.slots and intent.slots.intent != "general":
        # The existing Beauty executor owns TTL, ordinal and localized clarification semantics.
        return TaskPlan(
            tasks=["beauty"], stop_reason=("clarify_in_tool" if not sufficiency.ready else None)
        )
    return TaskPlan(tasks=["graph_chat"])


def verify_response(
    req: ChatRequest,
    decision: IntentDecision,
    plan: TaskPlan,
    response: ChatResponse,
    result: ToolResult,
) -> ChatResponse:
    ids = [p.id for p in response.products]
    if response.style_recipe is not None:
        recipe, context = response.style_recipe, req.style_context
        if (
            result.tool != "style"
            or context is None
            or (recipe.kind, recipe.look_id) != (context.kind, context.look_id)
        ):
            raise ApiError(502, "Invalid style identity", "invalid_tool_result")
        if response.style_context is None or (
            response.style_context.recipe_id,
            response.style_context.recipe_version,
            response.style_context.current_step,
        ) != (recipe.recipe_id, recipe.recipe_version, recipe.current_step):
            raise ApiError(502, "Invalid style progress", "invalid_tool_result")
        if set(ids) != {p.product_id for p in recipe.products if p.product_id}:
            raise ApiError(502, "Invalid style products", "invalid_tool_result")
        for product in recipe.products:
            if product.ar_eligible and not any(
                (e.product_id, e.shade_id, e.verification)
                == (product.product_id, product.shade_id, "verified")
                for e in result.evidence
            ):
                raise ApiError(502, "Invalid style selection evidence", "invalid_tool_result")
    if ids != result.product_ids or len(ids) != len(set(ids)):
        raise ApiError(502, "Inconsistent product references", "invalid_tool_result")
    if any(e.product_id not in ids for e in result.evidence) and result.tool != "ar_command":
        raise ApiError(502, "Invalid product evidence", "invalid_tool_result")
    if response.evidence is not None and [e.product_id for e in response.evidence] != ids:
        raise ApiError(502, "Inconsistent catalog evidence", "invalid_tool_result")
    if result.action_proposed or result.application != "not_requested":
        raise ApiError(502, "Tool cannot declare app execution", "invalid_tool_result")
    if result.tool not in plan.tasks and plan.tasks:
        raise ApiError(502, "Unexpected tool", "invalid_tool_result")
    if response.result_type == "recommendations" and any(
        check.verdict == "NOT_MATCH" for check in result.conditions
    ):
        raise ApiError(502, "Recommendation violates filters", "invalid_tool_result")
    if (
        result.tool == "beauty"
        and response.chat_context is not None
        and any(pid not in response.chat_context.candidate_ids for pid in ids)
    ):
        raise ApiError(502, "Product outside candidate list", "invalid_tool_result")
    if response.ar_result is not None:
        if req.request_type != "ar_command" or result.tool != "ar_command":
            raise ApiError(502, "Unexpected AR result", "invalid_tool_result")
        if response.ar_result.request_id != req.request_id:
            raise ApiError(502, "Unexpected AR request ID", "invalid_tool_result")
        proposal = response.ar_result.action_proposal
        if proposal:
            lip = req.ar_context.lip if req.ar_context else None
            if (
                not lip
                or proposal.product_id != lip.product_id
                or proposal.shade_id != lip.shade_id
                or proposal.expected_state_version != req.ar_context.state_version
            ):
                raise ApiError(502, "Invalid AR proposal context", "invalid_tool_result")
            result.action_proposed = True
            result.application = "awaiting_app_ack"
    response.supervisor = SupervisorResult(
        intent=decision,
        plan=plan,
        result=result,
        unavailable_tools=[] if _g5_enabled() else ["knowledge"],
    )
    return response


class ChatService:
    """Retrieves product candidates and asks the LLM to answer the user's question."""

    def __init__(
        self, graph: GraphReader | None, llm: Completer, catalog=None, requests=None, sessions=None
    ) -> None:
        self._graph = graph
        self._llm = llm
        self._catalog = catalog
        self._requests = requests
        self._sessions = sessions

    async def answer(self, req: ChatRequest, principal_key: str | None = None) -> ChatResponse:
        explicit_knowledge = req.request_type == "knowledge_consultation"
        if explicit_knowledge:
            # A knowledge hint must pass the same tool and session guards as ordinary chat.
            req = req.model_copy(update={"request_type": "chat"})
        context = resolve_context(req)
        decision = route_intent(context)
        if (_g5_enabled() or explicit_knowledge) and _is_knowledge_question(req, context, decision):
            return await self._run_supervisor(
                req, context, decision.model_copy(update={"intent": "knowledge"})
            )
        # G2 reuses the authoritative shopping session, including its CAS and TTL.
        # OFF and non-Korean chat keep their legacy stateless route.
        if (
            req.request_type == "chat"
            and req.locale == "ko"
            and get_settings().g1_supervisor_enabled
            and self._sessions is not None
            and req.style_context is None
            and decision.intent in {"general", "product", "ingredient"}
        ):
            req = req.model_copy(update={"request_type": "beauty_consultation"})
            context = resolve_context(req)
            decision = route_intent(context)
        if req.request_type == "style_consultation" and decision.intent in {
            "product",
            "ingredient",
        }:
            req = req.model_copy(update={"request_type": "beauty_consultation"})
            context = resolve_context(req)
            decision = route_intent(context)
        if (
            req.request_type == "beauty_consultation"
            and decision.intent != "style"
            and self._sessions is not None
        ):
            return await self._answer_session(req, principal_key)
        if req.request_type == "ar_command":
            # Preserve production closure and idempotency before invoking any tool or LLM.
            if get_settings().is_production:
                raise ApiError(
                    503, "AR request storage is not configured", "ar_requests_unavailable"
                )
            if not principal_key or self._requests is None or req.request_id is None:
                raise ApiError(503, "AR request storage is unavailable", "ar_requests_unavailable")
            fingerprint = sha256(req.model_dump_json().encode("utf-8")).hexdigest()
            return await self._requests.run(
                principal_key,
                req.request_id,
                fingerprint,
                lambda: self._run_supervisor(req, context, decision),
            )
        return await self._run_supervisor(req, context, decision)

    async def _interpret_beauty(self, req, *, pending=None):
        previous = req.chat_context
        followup = bool(previous and _look_search_followup(req.message))
        category = look_shopping_category(req.message) if req.style_context else None
        if req.style_context and followup and not category:
            category = previous.filters.category
        if not category:
            return await interpret_beauty(req, self._llm, pending=pending)
        if self._catalog is None:
            raise ApiError(503, "Catalog is not configured", "catalog_unavailable")
        style = req.style_context
        try:
            look = await self._catalog.get_style_look(style.kind, style.look_id)
        except UpstreamError as exc:
            raise ApiError(502, "Look is temporarily unavailable", "upstream_error") from exc
        if look is None or look.id != style.look_id:
            raise ApiError(404, "Look is unavailable", "style_look_not_found")
        profile = {
            "title": look.title,
            "category": category,
            "basis": "catalog metadata; not video analysis",
        }
        plan = await interpret_beauty(req, self._llm, profile)
        if plan.intent not in {"search", "refine"}:
            plan = plan.model_copy(
                update={
                    "intent": "search",
                    "scope": "catalog",
                    "ordinal": None,
                    "selection": None,
                    "compare_ordinals": [],
                }
            )
        if followup:
            plan = plan.model_copy(update={"intent": "refine", "scope": "previous"})
        elif not previous and plan.scope == "previous":
            plan = plan.model_copy(update={"intent": "search", "scope": "catalog"})
        query = _grounded_look_query(req.message, look.title, plan.query)
        return plan.model_copy(update={"category": category, "query": query})

    async def _run_supervisor(
        self,
        req: ChatRequest,
        context: ResolvedContext,
        decision: IntentDecision,
        *,
        thread_id: UUID | None = None,
        request_id: UUID | None = None,
        model_turn: G1ModelTurn | None = None,
    ) -> ChatResponse:
        if decision.intent == "knowledge":
            return await self._execute_turn(req, decision, self._plan_turn(context, decision))
        # AR can clarify missing selection without an LLM.
        if (
            not self._llm.configured
            and req.request_type != "ar_command"
            and req.request_type != "style_consultation"
            and decision.intent != "style"
        ):
            raise ApiError(503, "Chatbot is not configured", "chatbot_unavailable")
        use_graph = (
            req.request_type in {"chat", "beauty_consultation"}
            and decision.intent in {"general", "product", "ingredient"}
            and req.style_context is None
            and get_settings().g1_supervisor_enabled
        )
        if (
            use_graph
            and model_turn is None
            and decision.slots is None
            and thread_id is None
            and req.chat_context is None
        ):
            model_turn = await self._choose_g1_turn(req)
        if model_turn is not None:
            decision.slots = model_turn.plan
        free_category = None
        free_detail = False
        if use_graph and req.locale == "ko" and req.request_type == "chat":
            if not re.search(r"추천\s*(?:하지\s*마|말고|없이)|추천은\s*(?:빼|안)", req.message):
                free_category = look_shopping_category(req.message)
            free_detail = bool(
                req.screen_context
                and req.screen_context.product_id
                and re.search(r"색상|호수|색깔|가격|얼마|성분|향료", req.message)
            )
        if (free_category or free_detail) or (
            req.request_type == "beauty_consultation"
            and decision.intent
            not in {
                "compound",
                "style",
            }
        ):
            if self._catalog is None:
                raise ApiError(503, "Catalog is not configured", "catalog_unavailable")
            try:
                if decision.slots is None:
                    decision.slots = await self._interpret_beauty(req)
            except ApiError as exc:
                exc.supervisor_result = ToolResult(tool="beauty", status="error", reason=exc.code)
                raise
            if (
                model_turn is None
                and decision.slots.intent == "general"
                and (free_category or free_detail)
            ):
                decision.slots = decision.slots.model_copy(
                    update={
                        "intent": "detail" if free_detail else "search",
                        "category": free_category,
                    }
                )
            if decision.slots.intent != "general":
                decision.intent = "ingredient" if decision.intent == "ingredient" else "product"
        if use_graph:
            slots = decision.slots
            g1_catalog = bool(
                req.locale == "ko"
                and thread_id is None
                and slots
                and slots.scope == "catalog"
                and not slots.compare_ordinals
                and not direct_comparison(req, slots)
                and (
                    (slots.intent == "search" and req.chat_context is None)
                    or (
                        slots.intent in {"detail", "price"}
                        and req.screen_context
                        and req.screen_context.product_id
                    )
                )
            )
            state = VishueState(
                turn_id=uuid4(),
                request_id=request_id or req.request_id,
                thread_id=thread_id,
                result_set_id=context.result_set_id,
                state_version=context.session_version,
                locale=req.locale,
                decision=decision,
            )
            output = await product_supervisor.ainvoke(
                state,
                context=SupervisorRuntime(
                    req,
                    context,
                    self._plan_turn,
                    partial(self._execute_turn, g1_catalog=g1_catalog, model_turn=model_turn),
                ),
            )
            return output["response"]
        return await self._execute_turn(req, decision, self._plan_turn(context, decision))

    async def _choose_g1_turn(self, req: ChatRequest) -> G1ModelTurn | None:
        complete = getattr(self._llm, "complete_with_tools", None)
        if req.locale != "ko" or not get_settings().g1_supervisor_enabled or complete is None:
            return None
        if not self._llm.configured:
            raise ApiError(503, "Chatbot is not configured", "chatbot_unavailable")
        return await choose_g1_turn(req, complete)

    @staticmethod
    def _plan_turn(context: ResolvedContext, decision: IntentDecision) -> TaskPlan:
        return build_plan(context, decision, check_sufficiency(context, decision))

    async def _execute_turn(
        self,
        req: ChatRequest,
        decision: IntentDecision,
        plan: TaskPlan,
        *,
        g1_catalog=False,
        model_turn: G1ModelTurn | None = None,
    ) -> ChatResponse:
        tool = (
            plan.tasks[0] if plan.tasks else "ar_command" if decision.intent == "ar" else "beauty"
        )
        try:
            if model_turn and model_turn.answer is not None:
                response = ChatResponse(answer=model_turn.answer, products=[])
                result = ToolResult(tool="graph_chat", status="success")
            elif g1_catalog and tool == "beauty":
                catalog = G1CatalogTool(self._catalog, decision.slots.query or "")
                token = catalog_tool_call_id.set(model_turn.tool_call_id if model_turn else None)
                try:
                    response = await execute_beauty(req, decision.slots, catalog, g1=True)
                finally:
                    catalog_tool_call_id.reset(token)
                if response is None or response.tool_result is None:
                    raise ApiError(502, "Missing catalog result", "invalid_tool_result")
                if (
                    decision.slots.intent == "search"
                    and model_turn
                    and requests_general_explanation(req.message)
                ):
                    explanation = await explain_general_question(req, self._llm)
                    response.answer = f"{explanation}\n\n{response.answer}"
                result = response.tool_result
            else:
                if model_turn and model_turn.tool_call_id:
                    raise ApiError(502, "Unsupported G1 tool route", "invalid_tool_result")
                response, result = await self.execute_tool(req, decision, plan)
            response = verify_response(req, decision, plan, response, result)
            if model_turn and model_turn.tool_call_id:
                logger.info(
                    "g1_catalog_tool_result",
                    extra={
                        "tool_call_id": model_turn.tool_call_id,
                        "tool_name": (
                            "catalog.get_product_detail"
                            if model_turn.tool_name == DETAIL_TOOL
                            else "catalog.search_options"
                            if response.option_search is not None
                            else "catalog.search_products"
                        ),
                        "result_type": response.result_type,
                        "product_ids": result.product_ids,
                    },
                )
            return response
        except UpstreamError as exc:
            error = ApiError(502, "Chatbot is temporarily unavailable", "upstream_error")
            error.supervisor_result = ToolResult(tool=tool, status="error", reason="upstream_error")
            raise error from exc
        except ApiError as exc:
            exc.supervisor_result = ToolResult(
                tool=tool,
                status="error",
                reason=exc.code,
                conditions=[ConditionCheck(condition="tool", verdict="ERROR", reason=exc.code)],
            )
            raise

    @staticmethod
    def _cached_session_response(state):
        response = ChatResponse.model_validate(state.last_response)
        response.supervisor = state.last_supervisor
        response.tool_result = state.last_tool_result
        return response

    async def _validate_session_context(self, context, incoming, screen, *, select_screen=False):
        original_ids = set(context.candidate_ids)
        ids = list(dict.fromkeys(context.candidate_ids + context.scope_ids))
        if len(ids) > 6:
            raise ApiError(422, "Invalid candidate scope", "invalid_chat_selection")
        rows = await self._catalog.search_products(ids=ids) if ids else []
        products = {p.id: p for p in rows if p.id in ids}
        if len(products) != len(ids):
            raise ApiError(422, "Catalog candidates changed; search again", "chat_catalog_changed")
        for option in context.option_scope or []:
            product = products.get(option.product_id)
            if (
                product is None
                or not option.option_id
                or (
                    option.shade_id not in {s.id for s in product.shades}
                    if product.shades
                    else option.shade_id is not None
                )
            ):
                raise ApiError(422, "Catalog option scope changed", "chat_catalog_changed")
        for pid, sid in context.shade_selections.items():
            if pid not in products or not any(s.id == sid for s in products[pid].shades):
                raise ApiError(422, "Catalog shade changed", "chat_catalog_changed")
        if screen and screen.product_id:
            product = products.get(screen.product_id) or await self._catalog.get_product(
                screen.product_id
            )
            if (
                product is None
                or product.id != screen.product_id
                or (screen.shade_id and not any(s.id == screen.shade_id for s in product.shades))
            ):
                raise ApiError(422, "Invalid screen selection", "invalid_chat_selection")
            products[product.id] = product
            if select_screen and product.id not in context.candidate_ids:
                context.candidate_ids = [product.id]
                context.scope_ids = [product.id]
                context.option_scope = None
                context.selected_product_id = product.id
                context.shade_selections = {product.id: screen.shade_id} if screen.shade_id else {}
        if incoming:
            if incoming.selected_product_id:
                if incoming.selected_product_id in context.candidate_ids:
                    context.selected_product_id = incoming.selected_product_id
                elif incoming.selected_product_id not in original_ids and (
                    not screen or incoming.selected_product_id != screen.product_id
                ):
                    raise ApiError(422, "Invalid selected product", "invalid_chat_selection")
            for pid, sid in incoming.shade_selections.items():
                if pid not in products or not any(s.id == sid for s in products[pid].shades):
                    raise ApiError(422, "Invalid selected shade", "invalid_chat_selection")
                if pid in context.candidate_ids:
                    context.shade_selections[pid] = sid
        if (
            select_screen
            and screen
            and screen.screen_id in ("product-detail", *COMPARISON_SCREENS)
            and screen.product_id
        ):
            context.selected_product_id = screen.product_id
            if screen.shade_id:
                context.shade_selections[screen.product_id] = screen.shade_id
            else:
                context.shade_selections.pop(screen.product_id, None)
        return context

    async def _answer_session(self, incoming: ChatRequest, owner: str | None):
        if not owner or not owner.startswith(("user:", "guest:")):
            raise ApiError(401, "Chat principal required", "chat_session_owner_required")
        repo = self._sessions
        ref = incoming.chat_context.session if incoming.chat_context else None
        fingerprint = sha256(
            json.dumps(
                incoming.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        request_id = incoming.request_id or uuid5(
            NAMESPACE_URL, f"{owner}:{ref.session_id if ref else 'bootstrap'}:{fingerprint}"
        )
        state, load_error = None, None
        if ref is None:
            try:
                await repo.check_new_request(owner, request_id)
            except ApiError as exc:
                if exc.code != "chat_session_unavailable":
                    raise
                load_error = exc
        if ref:
            try:
                state = await repo.load(owner, ref)
            except ApiError as exc:
                if incoming.locale == "ko" and get_settings().g1_supervisor_enabled:
                    # A supplied capability must be valid before any model or Catalog call.
                    raise
                if exc.code not in {"chat_session_unavailable", "chat_session_expired"}:
                    raise
                load_error = exc
            if state:
                if state.last_request_id == request_id:
                    if state.last_fingerprint != fingerprint:
                        raise ApiError(409, "Request ID content changed", "chat_request_conflict")
                    return self._cached_session_response(state)
                if (
                    ref.state_version != state.state_version
                    or ref.result_set_id != state.result_set_id
                ):
                    raise ApiError(409, "Chat result set changed", "chat_session_conflict")
        req = incoming.model_copy(deep=True)
        g2_enabled = req.locale == "ko" and get_settings().g1_supervisor_enabled
        general_only = g2_enabled and req.general_makeup
        old_pending = state.pending_clarification if state and g2_enabled else None
        if (
            g2_enabled
            and incoming.clarification_id
            and (not old_pending or incoming.clarification_id != old_pending.id)
        ):
            raise ApiError(409, "Clarification changed", "chat_clarification_conflict")
        focus_changed = bool(
            old_pending
            and (
                (
                    incoming.screen_context
                    and incoming.screen_context.product_id
                    and incoming.screen_context.product_id != old_pending.product_id
                    and not incoming.clarification_id
                )
                or (
                    incoming.chat_context
                    and incoming.chat_context.selected_product_id
                    and incoming.chat_context.selected_product_id != old_pending.product_id
                    and (
                        not incoming.clarification_id
                        or incoming.chat_context.selected_product_id
                        != state.context.selected_product_id
                    )
                )
                or (
                    not incoming.clarification_id
                    and incoming.chat_context
                    and incoming.chat_context.shade_selections != state.context.shade_selections
                )
            )
        )
        active_pending = old_pending if incoming.clarification_id and not focus_changed else None
        resolved_target = active_pending.product_id if active_pending else None
        cancelled = bool(old_pending and _cancels_pending(req.message))
        goal_changed = bool(old_pending and abandons_ingredient_goal(req))
        if general_only:
            req.screen_context = None
            req.style_context = None
        # Client candidate lists/filters are never promoted into a server-owned snapshot.
        req.chat_context = state.context.model_copy(deep=True) if state else None
        if resolved_target:
            req.chat_context.selected_product_id = resolved_target
            if req.screen_context and req.screen_context.product_id != resolved_target:
                req.screen_context = None  # Same question ID: old screen is not a new selection.
        if focus_changed and general_only:
            try:
                await self._validate_session_context(req.chat_context, incoming.chat_context, None)
            except UpstreamError as exc:
                raise ApiError(502, "Catalog validation failed", "upstream_error") from exc
        context = resolve_context(req)
        if state:
            context.state_source = "server_session"
            context.session_version = state.state_version
            context.result_set_id = str(state.result_set_id)
        decision = route_intent(context)
        if general_only:
            decision.intent = "general"
        if decision.intent == "compound":
            return await self._run_supervisor(req, context, decision)
        model_turn = (
            await self._choose_g1_turn(req)
            if ref is None
            and not general_only
            and not cancelled
            and not req.recent_messages
            and not (
                g2_enabled and _G2_FILTER.search(req.message) and _FILTER_CHANGE.search(req.message)
            )
            and incoming.chat_context is None
            and req.style_context is None
            and decision.intent in {"general", "product", "ingredient"}
            else None
        )
        registered_plan = None
        if (
            active_pending
            and active_pending.missing_slot == "shade"
            and active_pending.product_id
            and not (general_only or cancelled or goal_changed)
        ):
            try:
                product = await self._catalog.get_product(active_pending.product_id)
            except UpstreamError as exc:
                raise ApiError(502, "Catalog validation failed", "upstream_error") from exc
            if product and product.id == active_pending.product_id:
                # An exact Catalog option answer must not become a new LLM product search.
                matches = [
                    s for s in product.shades if _shade_label(s.name) == _shade_label(req.message)
                ]
                if matches:
                    registered_plan = (
                        SearchPlan(intent="detail", scope="previous", shade_name=matches[0].name)
                        if len(matches) == 1
                        else SearchPlan(intent="general")
                    )
        decision.slots = (
            SearchPlan(intent="general")
            if general_only or cancelled
            else registered_plan
            if registered_plan is not None
            else model_turn.plan
            if model_turn
            else await self._interpret_beauty(req, pending=active_pending)
        )
        slots = decision.slots
        if (
            req.recent_messages
            and ref is None
            and incoming.chat_context is None
            and not general_only
            and req.style_context is None
            and slots.intent == "search"
            and slots.scope == "catalog"
            and not slots.ordinal
            and not slots.selection
            and not slots.compare_ordinals
            and not (_G2_FILTER.search(req.message) and _FILTER_CHANGE.search(req.message))
        ):
            # History helps classify the turn; an independent search still uses G1 tools.
            model_turn = await self._choose_g1_turn(req)
            if model_turn:
                slots = decision.slots = model_turn.plan
        if (
            active_pending
            and active_pending.product_id
            and slots.intent in {"detail", "price"}
            and (slots.ordinal is not None or slots.query is not None)
        ):
            target = await _resolve_product_reference(req.chat_context, slots, self._catalog)
            if target and target != active_pending.product_id:
                focus_changed = True
                resolved_target = target
                req.chat_context.selected_product_id = target
                req.screen_context = None
                active_pending = None
        if goal_changed:
            active_pending = None
        if active_pending and slots.intent == "detail" and not cancelled and not general_only:
            slots.ingredient_lookup = True
            if not slots.ingredient_name and not slots.ingredient_conditions:
                slots.ingredient_conditions = [
                    IngredientPlanCondition(ingredient_name=c.ingredient_name, operator=c.operator)
                    for c in active_pending.ingredient_conditions
                ]
        pending_ambiguous = False
        if cancelled:
            model_turn = G1ModelTurn(slots, answer="성분 확인 질문을 취소했어요.")
        elif (
            active_pending
            and slots.intent == "general"
            and not general_only
            and (
                registered_plan is not None or not re.search(r"설명|방법|어떻게|알려", req.message)
            )
        ):
            pending_ambiguous = True
            model_turn = G1ModelTurn(
                slots,
                answer=(
                    "확인할 상품을 선택해 주세요."
                    if active_pending.missing_slot == "product"
                    else "확인할 상품의 호수를 선택해 주세요."
                ),
            )
        unsupported = g2_enabled and not general_only and _unsupported_g2_change(req.message, slots)
        if unsupported:
            slots = decision.slots = SearchPlan(intent="general")
            model_turn = G1ModelTurn(
                slots,
                answer=(
                    "요청한 조건 중 현재 확인하거나 적용할 수 없는 조건이 있어 변경하지 않았어요. "
                    "상품에 등록된 매트 제형이나 가격 조건으로 "
                    "바꾸거나, 적용할 조건을 구체적으로 알려 주세요."
                ),
            )
        if (
            (state or general_only)
            and model_turn is None
            and slots.intent == "general"
            and req.locale == "ko"
            and get_settings().g1_supervisor_enabled
        ):
            # General interludes do not retrieve unrequested products from the legacy graph.
            try:
                answer = await self._llm.complete(build_messages(req, []))
            except UpstreamError as exc:
                raise ApiError(502, "Chatbot is temporarily unavailable", "upstream_error") from exc
            if not isinstance(answer, str) or not answer.strip():
                raise ApiError(502, "Invalid general answer", "invalid_tool_result")
            model_turn = G1ModelTurn(slots, answer=answer.strip())
        if (
            g2_enabled
            and slots.intent in {"search", "refine"}
            and refers_to_same_budget(req.message)
        ):
            if state:
                slots.intent = "refine"
            elif ref is None and not load_error:
                slots.intent = "search"
                slots.scope = "catalog"
        comparing = direct_comparison(req, slots)
        independent = (
            slots.intent == "general"
            or (comparing and req.screen_context and req.screen_context.product_id)
            or (
                slots.intent == "search"
                and slots.scope == "catalog"
                and not slots.ordinal
                and not slots.compare_ordinals
                and not slots.selection
            )
            or (
                slots.intent in {"detail", "price"}
                and req.screen_context
                and req.screen_context.product_id
                and (slots.intent == "detail" or req.screen_context.screen_id == "product-detail")
                and not slots.ordinal
                and not slots.compare_ordinals
                and not slots.selection
            )
        )
        if (
            g2_enabled
            and not state
            and ref is None
            and slots.intent == "detail"
            and (slots.ingredient_lookup or slots.ingredient_name or slots.ingredient_conditions)
            and not (req.screen_context and req.screen_context.product_id)
        ):
            return ChatResponse(
                answer="성분을 확인할 상품과 호수를 선택해 주세요.",
                products=[],
                result_type="clarification",
            )
        if not state and not independent:
            if load_error:
                raise load_error
            if repo.client is None:
                raise ApiError(503, "Chat session storage unavailable", "chat_session_unavailable")
            raise ApiError(
                409, "A server result set is required; search again", "chat_session_required"
            )
        if (
            not state
            and req.screen_context
            and (req.screen_context.screen_id == "product-detail" or comparing)
            and independent
            and slots.intent in {"detail", "price"}
            # The G1 detail tool validates product and shade before selecting them.
            # Let it return a clarification for a mismatched screen shade.
            and not (model_turn and model_turn.tool_name == DETAIL_TOOL)
        ):
            req.chat_context = await self._validate_session_context(
                BeautyContext(issued_at=int(time.time()), filters=BeautyFilters()),
                None,
                req.screen_context,
                select_screen=True,
            )
        elif slots.intent == "search" and independent:
            # Reset stale Catalog references, but retain server-owned ingredient constraints.
            req.chat_context = (
                BeautyContext(
                    issued_at=int(time.time()),
                    filters=BeautyFilters(
                        ingredient_conditions=state.context.filters.model_copy(
                            deep=True
                        ).ingredient_conditions
                    ),
                )
                if state
                else None
            )
            req.screen_context = None
        elif state and slots.intent != "general":
            if (
                req.screen_context
                and req.screen_context.screen_id not in ("product-detail", *COMPARISON_SCREENS)
                and req.screen_context.product_id in req.chat_context.candidate_ids
                and incoming.chat_context.selected_product_id
                and incoming.chat_context.selected_product_id != req.screen_context.product_id
            ):
                req.screen_context = None
            try:
                await self._validate_session_context(
                    req.chat_context,
                    incoming.chat_context.model_copy(
                        update={"selected_product_id": resolved_target}
                    )
                    if resolved_target
                    else incoming.chat_context,
                    req.screen_context,
                    select_screen=(
                        bool(
                            not req.chat_context.selected_product_id
                            and not incoming.chat_context.selected_product_id
                            and req.screen_context
                            and req.screen_context.product_id in req.chat_context.candidate_ids
                        )
                        if comparing
                        else not slots.ordinal
                        and not slots.compare_ordinals
                        and not slots.selection
                    ),
                )
            except UpstreamError as exc:
                raise ApiError(502, "Catalog validation failed", "upstream_error") from exc
        context = resolve_context(req)
        if state:
            context.state_source = "server_session"
            context.session_version = state.state_version
            context.result_set_id = str(state.result_set_id)
        response = await self._run_supervisor(
            req,
            context,
            decision,
            thread_id=ref.session_id if state and ref else None,
            request_id=request_id,
            model_turn=model_turn,
        )
        result = response.supervisor.result
        if unsupported or pending_ambiguous:
            response.result_type = "clarification"
        ctx = response.chat_context
        if (
            ctx
            and req.chat_context
            and slots.intent in {"detail", "price"}
            and ctx.candidate_ids == req.chat_context.candidate_ids
            and ctx.filters.option_search
        ):
            ctx.option_scope = req.chat_context.option_scope
        next_pending = old_pending
        pending_changed = False
        if g2_enabled and state:
            errors = result.status == "error" or any(
                r.status == "error" or r.verdict == "ERROR"
                for r in response.ingredient_results or []
            )
            if not errors:
                if (
                    cancelled
                    or goal_changed
                    or focus_changed
                    or slots.intent in {"search", "refine"}
                ):
                    next_pending = None
                ingredient_detail = slots.intent == "detail" and (
                    slots.ingredient_lookup or slots.ingredient_name or slots.ingredient_conditions
                )
                if ingredient_detail:
                    missing = next(
                        (
                            r
                            for r in response.ingredient_results or []
                            if r.reason == "shade_required"
                        ),
                        None,
                    )
                    missing_product = bool(
                        ctx and not ctx.selected_product_id and not response.products
                    )
                    if missing or missing_product:
                        conditions = [
                            IngredientFilter.model_validate(c.model_dump())
                            for c in slots.ingredient_conditions
                        ]
                        if slots.ingredient_name:
                            conditions.append(
                                IngredientFilter(
                                    ingredient_name=slots.ingredient_name,
                                    operator=slots.ingredient_operator,
                                )
                            )
                        # Deduplicate the same condition before enforcing the existing limit.
                        conditions = list(
                            {(c.ingredient_name, c.operator): c for c in conditions}.values()
                        )
                        if len(conditions) > 6:
                            raise ApiError(400, "Too many ingredient conditions", "invalid_request")
                        slot = "shade" if missing else "product"
                        pid = missing.product_id if missing else None
                        if (
                            old_pending
                            and old_pending.missing_slot == slot
                            and old_pending.product_id == pid
                            and old_pending.ingredient_conditions == conditions
                        ):
                            next_pending = old_pending
                        else:
                            next_pending = PendingClarification(
                                id=uuid4(),
                                missing_slot=slot,
                                product_id=pid,
                                result_set_id=state.result_set_id,
                                created_request_id=request_id,
                                created_state_version=state.state_version + 1,
                                expires_at=state.expires_at,
                                ingredient_conditions=conditions,
                            )
                    elif response.ingredient_results:
                        next_pending = None
                pending_changed = next_pending != old_pending
            response.pending_clarification = next_pending
            if next_pending and response.result_type == "clarification" and not pending_changed:
                response.chat_context = state.context.model_copy(deep=True, update={"session": ref})
                response.session_status = "unchanged"
                return response
            if pending_changed and (ctx is None or next_pending):
                source = req.chat_context if focus_changed and general_only else state.context
                ctx = response.chat_context = source.model_copy(deep=True)
        if (
            state
            and ctx is None
            and not pending_changed
            and slots.intent == "general"
            and incoming.locale == "ko"
            and get_settings().g1_supervisor_enabled
        ):
            # An intervening explanation must not discard the previous result set.
            response.chat_context = state.context.model_copy(deep=True, update={"session": ref})
            response.session_status = "unchanged"
            return response
        if state and comparing and req.screen_context and req.screen_context.ingredient_comparison:
            response.chat_context = state.context.model_copy(deep=True, update={"session": ref})
            response.session_status = "unchanged"
            return response
        partial_ingredients = bool(response.products) and any(
            r.product_id in {p.id for p in response.products}
            and r.status != "error"
            and r.verdict != "ERROR"
            for r in response.ingredient_results or []
        )
        # An explicit detail filter change belongs to the existing search session
        # even if one ingredient lookup fails. Keep failed searches and unrelated
        # tool errors on their existing no-commit path.
        persist_failed_detail = bool(
            state
            and ctx
            and response.products
            and result.tool == "beauty"
            and slots.intent == "detail"
            and slots.persist_ingredient_conditions
            and (slots.ingredient_name or slots.ingredient_conditions)
            and ctx.candidate_ids == state.context.candidate_ids
            and ctx.scope_ids == state.context.scope_ids
            and all(p.id in state.context.candidate_ids for p in response.products)
        )
        if not pending_changed and (
            not ctx
            or result.status == "unsupported"
            or (result.status == "error" and not partial_ingredients and not persist_failed_detail)
            or (response.result_type == "clarification" and not response.products)
        ):
            if state and ctx:
                if not response.products:
                    response.chat_context = state.context.model_copy(deep=True)
                same_result_set = (
                    response.chat_context.option_scope == state.context.option_scope
                    and response.chat_context.candidate_ids == state.context.candidate_ids
                    and response.chat_context.scope_ids == state.context.scope_ids
                    and response.chat_context.filters == state.context.filters
                    # Positive selection hints replay on retry; None cannot clear a saved selection.
                    and (
                        response.chat_context.selected_product_id is not None
                        or state.context.selected_product_id is None
                    )
                )
                if same_result_set:
                    response.chat_context.session = ref
                    response.session_status = "unchanged"
                else:
                    # A failed replacement must never label new cards with the old capability.
                    response.chat_context.session = None
                    response.session_status = "unavailable"
                    response.answer += "\n" + TEXT[req.locale]["session_unavailable"]
            elif ctx and response.products and result.status == "error":
                ctx.session = None
                response.session_status = "unavailable"
                response.answer += "\n" + TEXT[req.locale]["session_unavailable"]
            return response
        try:
            await self._validate_session_context(ctx, None, None)
        except UpstreamError as exc:
            raise ApiError(502, "Catalog validation failed", "upstream_error") from exc
        now = int(time.time())
        renewed = state is None or (
            slots.intent in {"search", "refine"}
            or ctx.candidate_ids != state.context.candidate_ids
            or ctx.filters != state.context.filters
            or ctx.option_scope != state.context.option_scope
        )
        created = now if renewed else state.result_created_at
        ctx.issued_at = created
        token = ref.session_token if state else secrets.token_urlsafe(32)
        session_ref = ChatSessionRef(
            session_id=state.session_id if state else uuid4(),
            session_token=token,
            result_set_id=uuid4() if renewed else state.result_set_id,
            state_version=state.state_version + 1 if state else 1,
            expires_at=created + repo.ttl_seconds if renewed else state.expires_at,
        )
        ctx.session = session_ref
        response.session_status = "stored"
        canonical = ctx.model_copy(deep=True, update={"session": None})
        evidence_refs = {
            r["productId"]: r
            for r in (state.evidence_refs if state else [])
            if r["productId"] in ctx.candidate_ids
            and ctx.shade_selections.get(r["productId"]) == r["shadeId"]
        }
        for r in response.ingredient_results or []:
            evidence_refs.pop(r.product_id, None)
            if r.verified:
                evidence_refs[r.product_id] = {
                    "productId": r.product_id,
                    "shadeId": r.shade_id,
                    "evidenceId": r.evidence_id,
                    "sourceVersion": r.source_version,
                }
        snapshot = ChatSessionState(
            pending_clarification=next_pending,
            session_id=session_ref.session_id,
            owner=owner,
            owner_kind=owner.split(":", 1)[0],
            token_hash=sha256(token.encode()).hexdigest(),
            result_set_id=session_ref.result_set_id,
            state_version=session_ref.state_version,
            context=canonical,
            evidence_refs=list(evidence_refs.values()),
            created_at=state.created_at if state else now,
            result_created_at=created,
            expires_at=session_ref.expires_at,
            last_request_id=request_id,
            last_fingerprint=fingerprint,
            last_response=response.model_dump(mode="json"),
            last_supervisor=response.supervisor,
            last_tool_result=response.tool_result,
        )
        try:
            await repo.commit(snapshot, state.state_version if state else None)
        except ApiError as exc:
            if state and exc.status == 409:
                winner = await repo.load(owner, ref)
                if winner.last_request_id == request_id and winner.last_fingerprint == fingerprint:
                    return self._cached_session_response(winner)
            if exc.code != "chat_session_unavailable" or state:
                raise
            # A fresh independent answer can survive an outage, but is explicitly not persisted.
            ctx.session = None
            response.session_status = "unavailable"
            response.answer += "\n" + TEXT[req.locale]["session_unavailable"]
            result.status = "partial"
            result.conditions.append(
                ConditionCheck(
                    condition="session", verdict="ERROR", reason="chat_session_unavailable"
                )
            )
        return response

    async def execute_tool(
        self, req: ChatRequest, decision: IntentDecision, plan: TaskPlan
    ) -> tuple[ChatResponse, ToolResult]:
        if not plan.tasks or len(plan.tasks) > 1:
            if req.request_type == "style_consultation":
                return ChatResponse(
                    answer=STYLE_TEXT[req.locale]["unsupported"],
                    products=[],
                    style_status="unsupported",
                ), ToolResult(tool="style", status="unsupported", reason=plan.stop_reason)
            return (
                ChatResponse(answer=TEXT[req.locale]["clarify"], products=[]),
                ToolResult(tool="beauty", status="unsupported", reason=plan.stop_reason),
            )
        tool = plan.tasks[0]
        if tool == "ar_command":
            response = await self._propose_ar(req)
            ar = response.ar_result
            status = {
                "proposed": "success",
                "noop": "success",
                "clarification": "clarification",
                "unsupported": "unsupported",
            }[ar.status]
            proposal = ar.action_proposal
            evidence = (
                [
                    EvidenceRef(
                        product_id=proposal.product_id,
                        shade_id=proposal.shade_id,
                        source="catalog_api",
                        verification="verified",
                    )
                ]
                if proposal
                else []
            )
            return response, ToolResult(
                tool=tool, status=status, evidence=evidence, reason=ar.reason
            )
        if tool == "beauty":
            response = await execute_beauty(req, decision.slots, self._catalog)
            if response is None or response.tool_result is None:
                raise ApiError(502, "Missing catalog result", "invalid_tool_result")
            if (
                req.style_context
                and decision.slots.intent in {"search", "refine"}
                and (look_shopping_category(req.message) or _look_search_followup(req.message))
                and response.products
            ):
                response.answer += (
                    "\n"
                    + {
                        "ko": (
                            "룩의 제목과 상품 카테고리를 참고한 후보예요. "
                            "영상 속 사용 제품이나 색상은 확인되지 않았어요."
                        ),
                        "en": (
                            "These are catalog candidates based on the look title and category."
                            " The products and shades used in the video are unverified."
                        ),
                        "ja": (
                            "ルック名と商品カテゴリを参考にした候補です。"
                            "動画で使われた商品や色番は未確認です。"
                        ),
                        "zh": (
                            "这些是参考妆容标题与商品类别的目录候选。"
                            "视频中使用的产品和色号未经确认。"
                        ),
                    }[req.locale]
                )
            return response, response.tool_result
        if tool == "style":
            return await execute_style(req, self._catalog)
        if tool == "knowledge":
            if not _g5_enabled() or req.locale != "ko":
                return (
                    ChatResponse(answer=TEXT[req.locale]["clarify"], products=[]),
                    ToolResult(tool=tool, status="unsupported", reason="tool_unavailable"),
                )
            prior = _prior_knowledge_context(req)
            if prior:
                consultation = await consult_knowledge(req.message, prior_user_context=prior)
            else:
                consultation = await consult_knowledge(req.message)
            status = consultation.reply.status
            return (
                ChatResponse(answer=consultation.answer, products=[], knowledge=consultation.reply),
                ToolResult(
                    tool=tool,
                    status={
                        "answered": "success",
                        "partial": "partial",
                        "insufficient_evidence": "unsupported",
                        "error": "error",
                    }[status],
                    reason=None if status == "answered" else f"g5_{status}",
                ),
            )
        if tool != "graph_chat":
            raise ApiError(503, "Tool is not implemented", "tool_unavailable")
        graph = self._graph if self._graph is not None else GraphRepository(get_driver())
        products = await graph.find_products(extract_terms(req.message))
        answer = await self._llm.complete(build_messages(req, products))
        refs = [
            ProductRef(id=p.id, brand=p.brand, name=p.name, category=p.category) for p in products
        ]
        return ChatResponse(answer=answer, products=refs), ToolResult(
            tool=tool,
            status="partial",
            product_ids=[p.id for p in products],
            evidence=[
                EvidenceRef(
                    product_id=p.id,
                    source="neo4j",
                    verification="partial",
                    reason="graph_copy_not_canonical_revalidation",
                )
                for p in products
            ],
            reason="dedicated_tool_unavailable"
            if decision.intent in {"style", "ingredient"}
            else "legacy_graph_response",
        )

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
    sessions: ChatSessionRepository = Depends(get_chat_sessions),
) -> ChatService:
    return ChatService(None, llm, catalog, requests, sessions)
