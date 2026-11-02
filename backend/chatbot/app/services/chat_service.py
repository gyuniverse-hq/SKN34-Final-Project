import json
import re
import secrets
import time
from hashlib import sha256
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import Depends

from app.clients.catalog_client import CatalogClient, get_catalog_client
from app.clients.llm_client import LlmClient, get_llm_client
from app.core.config import get_settings
from app.core.errors import ApiError, UpstreamError
from app.core.graph import get_driver
from app.repositories.ar_command_repository import MemoryArRequestRepository, get_ar_requests
from app.repositories.chat_session_repository import ChatSessionRepository, get_chat_sessions
from app.repositories.graph_repository import GraphRepository
from app.schemas.chat import (
    ArAckRequest,
    ChatRequest,
    ChatResponse,
    ChatSessionRef,
    ChatSessionState,
    GraphProduct,
    ProductRef,
)
from app.schemas.supervisor import (
    ConditionCheck,
    EvidenceRef,
    IntentDecision,
    ResolvedContext,
    Sufficiency,
    SupervisorResult,
    TaskPlan,
    ToolResult,
)
from app.services.ar_command_service import propose_ar_command
from app.services.beauty_consultation_service import (
    TEXT,
    execute_beauty,
    interpret_beauty,
)
from app.services.style_recipe_service import TEXT as STYLE_TEXT
from app.services.style_recipe_service import execute_style

LANGUAGE = {"en": "English", "ko": "Korean", "ja": "Japanese", "zh": "Simplified Chinese"}
MAX_TERMS = 8
_WORD = re.compile(r"[\w가-힣ぁ-んァ-ン一-龥]{2,}")

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


def route_intent(context: ResolvedContext) -> IntentDecision:
    """Conservative routing hints; dedicated AR parsing still validates execution intent."""
    text = context.message.casefold()
    shopping = re.search(r"추천|recommend|おすすめ|推荐", text)
    execution = re.search(r"발라|적용해|설정해|조절해|apply|set .*intensity|塗って|涂上", text)
    intent = "general"
    if shopping and execution:
        intent = "compound"
    elif context.request_type == "ar_command":
        intent = "ar"
    elif (
        context.request_type == "style_consultation"
        or (context.request_type == "chat" and context.style is not None)
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
    response.supervisor = SupervisorResult(intent=decision, plan=plan, result=result)
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
        if req.request_type == "beauty_consultation" and self._sessions is not None:
            return await self._answer_session(req, principal_key)
        context = resolve_context(req)
        decision = route_intent(context)
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

    async def _run_supervisor(
        self, req: ChatRequest, context: ResolvedContext, decision: IntentDecision
    ) -> ChatResponse:
        # AR can clarify missing selection without an LLM.
        if (
            not self._llm.configured
            and req.request_type != "ar_command"
            and req.request_type != "style_consultation"
            and decision.intent != "style"
        ):
            raise ApiError(503, "Chatbot is not configured", "chatbot_unavailable")
        if req.request_type == "beauty_consultation" and decision.intent not in {
            "compound",
            "style",
        }:
            if self._catalog is None:
                raise ApiError(503, "Catalog is not configured", "catalog_unavailable")
            try:
                if decision.slots is None:
                    decision.slots = await interpret_beauty(req, self._llm)
            except ApiError as exc:
                exc.supervisor_result = ToolResult(tool="beauty", status="error", reason=exc.code)
                raise
            if decision.slots.intent != "general":
                decision.intent = "ingredient" if decision.intent == "ingredient" else "product"
        sufficient = check_sufficiency(context, decision)
        plan = build_plan(context, decision, sufficient)
        tool = (
            plan.tasks[0] if plan.tasks else "ar_command" if decision.intent == "ar" else "beauty"
        )
        try:
            response, result = await self.execute_tool(req, decision, plan)
            return verify_response(req, decision, plan, response, result)
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
        # Client candidate lists/filters are never promoted into a server-owned snapshot.
        req.chat_context = state.context.model_copy(deep=True) if state else None
        context = resolve_context(req)
        if state:
            context.state_source = "server_session"
            context.session_version = state.state_version
            context.result_set_id = str(state.result_set_id)
        decision = route_intent(context)
        if decision.intent == "compound":
            return await self._run_supervisor(req, context, decision)
        decision.slots = await interpret_beauty(req, self._llm)
        slots = decision.slots
        independent = (
            slots.intent == "general"
            or (
                slots.intent == "search"
                and slots.scope == "catalog"
                and not slots.ordinal
                and not slots.compare_ordinals
                and not slots.selection
            )
            or (
                slots.intent == "detail"
                and req.screen_context
                and req.screen_context.product_id
                and not slots.ordinal
                and not slots.compare_ordinals
                and not slots.selection
            )
        )
        if not state and not independent:
            if load_error:
                raise load_error
            if repo.client is None:
                raise ApiError(503, "Chat session storage unavailable", "chat_session_unavailable")
            raise ApiError(
                409, "A server result set is required; search again", "chat_session_required"
            )
        if slots.intent == "search" and independent:
            req.chat_context = (
                None  # A fresh search must work even if prior Catalog rows disappeared.
            )
            req.screen_context = None
        elif state and slots.intent != "general":
            if (
                req.screen_context
                and req.screen_context.product_id in req.chat_context.candidate_ids
                and incoming.chat_context.selected_product_id
                and incoming.chat_context.selected_product_id != req.screen_context.product_id
            ):
                req.screen_context = None
            try:
                await self._validate_session_context(
                    req.chat_context,
                    incoming.chat_context,
                    req.screen_context,
                    select_screen=not slots.ordinal
                    and not slots.compare_ordinals
                    and not slots.selection,
                )
            except UpstreamError as exc:
                raise ApiError(502, "Catalog validation failed", "upstream_error") from exc
        context = resolve_context(req)
        if state:
            context.state_source = "server_session"
            context.session_version = state.state_version
            context.result_set_id = str(state.result_set_id)
        response = await self._run_supervisor(req, context, decision)
        result = response.supervisor.result
        ctx = response.chat_context
        if (
            not ctx
            or result.status in {"error", "unsupported"}
            or (response.result_type == "clarification" and not response.products)
        ):
            if state and ctx:
                if not response.products:
                    response.chat_context = state.context.model_copy(deep=True)
                response.chat_context.session = ref
                response.session_status = "unchanged"
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
            return response, response.tool_result
        if tool == "style":
            return await execute_style(req, self._catalog)
        if tool == "knowledge":
            return (
                ChatResponse(answer=TEXT[req.locale]["clarify"], products=[]),
                ToolResult(tool=tool, status="unsupported", reason="tool_unavailable"),
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
