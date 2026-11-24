from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.models.ar_personalization import ArActivityEventRow
from app.models.cart_recommendation import CartRecommendationVisitRow
from app.models.member import MemberRow
from app.models.order import OrderLineRow, OrderRow
from app.models.recommendation_feedback import (
    RecommendationCandidateRow,
    RecommendationImpressionRow,
    RecommendationRequestRow,
    SkincareRecommendationEventRow,
    UserBehaviorEventRow,
)
from app.repositories.cart_recommendation_repository import CART_EVENT_SCHEMA, CART_SURFACE
from app.schemas.recommendation_feedback import SKINCARE_HISTORY_CONTRACT

AR_CHECKOUT_SURFACE = "ar_checkout"
AR_CHECKOUT_SCHEMA = "ar-checkout-v1"
AR_PURCHASE_KEY_PREFIX = "ar-purchase:"


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        order: OrderRow,
        *,
        ar_cart_events: list[list[UUID]],
        ar_terms: str | None,
        skincare_cart_events: list[list[UUID]],
        cart_visit_id: UUID | None = None,
        cart_recommendation_events: list[list[UUID]] | None = None,
    ) -> None:
        if cart_visit_id and ar_terms:
            await self._attach_cart_recommendation_sources(
                order,
                cart_visit_id,
                cart_recommendation_events or [],
                ar_terms,
            )
        self._session.add(order)
        if ar_terms and any(ar_cart_events):
            await self._session.flush()
            await self._attach_ar_checkout_sources(order, ar_cart_events, ar_terms)
        if any(skincare_cart_events):
            await self._session.flush()
            await self._attach_skincare_checkout_sources(order, skincare_cart_events)
        await self._session.commit()

    async def get(self, order_id: str, *, lock: bool = False) -> OrderRow | None:
        query = (
            select(OrderRow).options(selectinload(OrderRow.lines)).where(OrderRow.id == order_id)
        )
        return await self._session.scalar(query.with_for_update() if lock else query)

    async def _attach_cart_recommendation_sources(self, order, visit_id, cart_events, terms):
        visit = CartRecommendationVisitRow
        owner_visit = await self._session.scalar(
            select(visit.id)
            .join(MemberRow, MemberRow.id == visit.member_id)
            .where(
                visit.id == visit_id,
                visit.member_id == order.user_id,
                MemberRow.terms_version == terms,
            )
            .with_for_update(read=True, key_share=True)
        )
        if owner_visit is None:
            return
        order.cart_visit_id = owner_visit
        ids = {key for keys in cart_events for key in keys}
        if not ids:
            return
        event = UserBehaviorEventRow
        sources = await self._session.execute(
            select(event.event_id, event.product_id, event.option_id).where(
                event.event_id.in_(ids),
                event.member_id == order.user_id,
                event.session_id == owner_visit,
                event.event_type == "cart_add",
                event.event_source == "client",
                event.surface == CART_SURFACE,
                event.event_schema_version == CART_EVENT_SCHEMA,
            )
        )
        by_id = {key: (product, option) for key, product, option in sources}
        for line, keys in zip(order.lines, cart_events, strict=True):
            for key in keys:
                if by_id.get(key) == (line.product_id, line.shade_id):
                    line.cart_recommendation_event_id = key
                    del by_id[key]
                    break

    async def _attach_ar_checkout_sources(self, order, cart_events, terms):
        ids = {event_id for candidates in cart_events for event_id in candidates}
        sources = await self._session.scalars(
            select(ArActivityEventRow)
            .join(MemberRow, MemberRow.id == ArActivityEventRow.member_id)
            .where(
                MemberRow.terms_version == terms,
                ArActivityEventRow.member_id == order.user_id,
                ArActivityEventRow.event_id.in_(ids),
                ArActivityEventRow.event_type == "cart_add",
                ArActivityEventRow.impression_id.is_not(None),
            )
        )
        by_id = {event.event_id: event for event in sources}
        already_paid = set(
            await self._session.scalars(
                select(UserBehaviorEventRow.source_record_key).where(
                    UserBehaviorEventRow.event_source == "server",
                    UserBehaviorEventRow.event_type == "purchase_confirmed",
                    UserBehaviorEventRow.source_record_key.in_(
                        [f"{AR_PURCHASE_KEY_PREFIX}{event_id}" for event_id in by_id]
                    ),
                )
            )
        )
        used = set()
        for line, candidates in zip(order.lines, cart_events, strict=True):
            source = next(
                (
                    by_id[event_id]
                    for event_id in candidates
                    if event_id in by_id
                    and event_id not in used
                    and f"{AR_PURCHASE_KEY_PREFIX}{event_id}" not in already_paid
                    and (by_id[event_id].product_id, by_id[event_id].shade_id)
                    == (line.product_id, line.shade_id)
                ),
                None,
            )
            if source is None:
                continue
            used.add(source.event_id)
            # Link the verified cart event before opening the payment flow.
            self._session.add(
                UserBehaviorEventRow(
                    event_id=uuid4(),
                    member_id=order.user_id,
                    session_id=source.session_id,
                    order_line_id=line.id,
                    product_id=line.product_id,
                    option_id=line.shade_id,
                    event_type="cart_add",
                    event_source="server",
                    occurred_at=source.occurred_at,
                    attribution_policy_version=AR_CHECKOUT_SCHEMA,
                    source_record_key=f"ar-checkout:{line.id}",
                    event_schema_version=AR_CHECKOUT_SCHEMA,
                    surface=AR_CHECKOUT_SURFACE,
                    context_snapshot={
                        "ar_cart_event_id": str(source.event_id),
                        "ar_impression_id": str(source.impression_id),
                    },
                )
            )

    async def _attach_skincare_checkout_sources(
        self, order: OrderRow, cart_events: list[list[UUID]]
    ) -> None:
        event = SkincareRecommendationEventRow
        paid = aliased(event)
        ids = {event_id for candidates in cart_events for event_id in candidates}
        sources = await self._session.execute(
            select(event, RecommendationCandidateRow.product_id)
            .select_from(event)
            .join(
                RecommendationImpressionRow,
                RecommendationImpressionRow.impression_id == event.impression_id,
            )
            .join(
                RecommendationCandidateRow,
                RecommendationCandidateRow.candidate_id == RecommendationImpressionRow.candidate_id,
            )
            .join(
                RecommendationRequestRow,
                RecommendationRequestRow.request_id == RecommendationCandidateRow.request_id,
            )
            .where(
                event.event_id.in_(ids),
                event.event_type == "cart_add",
                RecommendationRequestRow.member_id == order.user_id,
                RecommendationRequestRow.contract_version == SKINCARE_HISTORY_CONTRACT,
                ~select(paid.event_id)
                .where(
                    paid.cart_event_id == event.event_id, paid.event_type == "purchase_confirmed"
                )
                .exists(),
            )
        )
        by_id = {source.event_id: (source, product_id) for source, product_id in sources}
        for line, candidates in zip(order.lines, cart_events, strict=True):
            source_id = next(
                (key for key in candidates if key in by_id and by_id[key][1] == line.product_id),
                None,
            )
            if source_id is None:
                continue
            source, _ = by_id.pop(source_id)
            self._session.add(
                event(
                    event_id=uuid4(),
                    impression_id=source.impression_id,
                    event_type="checkout_started",
                    occurred_at=datetime.now(UTC),
                    order_line_id=line.id,
                    cart_event_id=source_id,
                )
            )

    async def mark_paid(
        self, order: OrderRow, payment_key: str, *, ar_terms: str | None, skincare_feedback: bool
    ) -> None:
        order.status = "paid"
        order.payment_key = payment_key
        order.paid_at = datetime.now(UTC)
        if ar_terms:
            await self._record_ar_purchases(order, ar_terms)
        if skincare_feedback:
            await self._record_skincare_purchases(order)
        await self._session.commit()

    async def _record_skincare_purchases(self, order: OrderRow) -> None:
        event = SkincareRecommendationEventRow
        sources = await self._session.scalars(
            select(event)
            .join(OrderLineRow)
            .where(OrderLineRow.order_id == order.id, event.event_type == "checkout_started")
            .order_by(event.cart_event_id)
        )
        paid_at = datetime.now(UTC)
        for source in sources:
            await self._session.execute(
                insert(event)
                .values(
                    event_id=uuid4(),
                    impression_id=source.impression_id,
                    event_type="purchase_confirmed",
                    occurred_at=paid_at,
                    order_line_id=source.order_line_id,
                    cart_event_id=source.cart_event_id,
                )
                .on_conflict_do_nothing()
            )

    async def _record_ar_purchases(self, order, terms):
        sources = await self._session.scalars(
            select(UserBehaviorEventRow)
            .join(OrderLineRow, OrderLineRow.id == UserBehaviorEventRow.order_line_id)
            .join(MemberRow, MemberRow.id == UserBehaviorEventRow.member_id)
            .where(
                OrderLineRow.order_id == order.id,
                UserBehaviorEventRow.member_id == order.user_id,
                MemberRow.terms_version == terms,
                UserBehaviorEventRow.event_type == "cart_add",
                UserBehaviorEventRow.event_source == "server",
                UserBehaviorEventRow.surface == AR_CHECKOUT_SURFACE,
                UserBehaviorEventRow.event_schema_version == AR_CHECKOUT_SCHEMA,
            )
            # Concurrent orders can share sources. Take unique-index locks in the same order.
            .order_by(UserBehaviorEventRow.context_snapshot["ar_cart_event_id"].astext)
        )
        paid_at = datetime.now(UTC)
        for source in sources:
            await self._session.execute(
                insert(UserBehaviorEventRow)
                .values(
                    event_id=uuid4(),
                    member_id=source.member_id,
                    session_id=source.session_id,
                    order_line_id=source.order_line_id,
                    product_id=source.product_id,
                    option_id=source.option_id,
                    event_type="purchase_confirmed",
                    event_source="server",
                    occurred_at=paid_at,
                    attribution_policy_version=AR_CHECKOUT_SCHEMA,
                    source_record_key=(
                        f"{AR_PURCHASE_KEY_PREFIX}{source.context_snapshot['ar_cart_event_id']}"
                    ),
                    event_schema_version=AR_CHECKOUT_SCHEMA,
                    surface=AR_CHECKOUT_SURFACE,
                    context_snapshot=source.context_snapshot,
                )
                .on_conflict_do_nothing()
            )

    @staticmethod
    def line(**values: object) -> OrderLineRow:
        return OrderLineRow(**values)
