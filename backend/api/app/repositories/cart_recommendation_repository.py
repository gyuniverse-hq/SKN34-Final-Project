from datetime import UTC, datetime

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError
from app.models.admin import ProductAdminStateRow
from app.models.cart_recommendation import (
    CartRecommendationImpressionRow as Impression,
)
from app.models.cart_recommendation import (
    CartRecommendationVisitRow as Visit,
)
from app.models.catalog import ProductRow, ShadeRow
from app.models.recommendation_feedback import UserBehaviorEventRow as Event
from app.schemas.cart_recommendation import CartRecommendationCandidate

CART_SURFACE = "cart_recommendations"
CART_EVENT_SCHEMA = "cart-recommendation-v1"


def conflict():
    return ApiError(409, "Cart recommendation identity conflict", "cart_recommendation_conflict")


class CartRecommendationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def lock_visit(self, visit_id):
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"cart-recommendation:{visit_id}"},
        )
        return await self.db.get(Visit, visit_id)

    async def catalog(self, product_ids):
        query = (
            select(
                ProductRow.id,
                ProductRow.makeup_zone,
                ShadeRow.id,
                ShadeRow.hex,
                ProductRow.texture,
                ShadeRow.measure_method,
                ShadeRow.color_source,
            )
            .outerjoin(ShadeRow)
            .where(
                ProductRow.price_krw > 0,
                or_(ProductRow.makeup_zone.in_(("lip", "blush")), ProductRow.id.in_(product_ids)),
            )
        )
        if get_settings().admin_enabled:
            unavailable = select(ProductAdminStateRow.product_id).where(
                or_(ProductAdminStateRow.is_visible.is_(False), ProductAdminStateRow.stock == 0)
            )
            query = query.where(ProductRow.id.not_in(unavailable))
        return await self.db.execute(query)

    async def save_visit(self, owner, experiment, arm, visit_id, basket, candidates):
        self.db.add(
            Visit(
                id=visit_id,
                member_id=owner,
                experiment=experiment,
                arm=arm,
                basket=basket,
                candidates=[
                    candidate.model_dump(mode="json", by_alias=False) for candidate in candidates
                ],
            )
        )
        await self.db.commit()

    @staticmethod
    def _candidate(visit, candidate_id):
        return next(
            (
                CartRecommendationCandidate.model_validate(row)
                for row in visit.candidates
                if row["candidate_id"] == str(candidate_id)
            ),
            None,
        )

    async def impression(self, owner, experiment, body):
        visit = await self.db.get(Visit, body.cart_visit_id)
        if (
            visit is None
            or visit.member_id != owner
            or visit.experiment != experiment
            or self._candidate(visit, body.candidate_id) is None
        ):
            raise conflict()
        impression_id = await self.db.scalar(
            insert(Impression)
            .values(
                id=body.impression_id,
                candidate_id=body.candidate_id,
                visit_id=visit.id,
                visibility_policy=body.visibility_policy,
            )
            .on_conflict_do_nothing()
            .returning(Impression.id)
        )
        if impression_id is None:
            impression_id = await self.db.scalar(
                select(Impression.id).where(
                    Impression.visit_id == visit.id,
                    Impression.candidate_id == body.candidate_id,
                )
            )
            if impression_id is None:
                raise conflict()
        await self.db.commit()
        return impression_id

    async def cart_add(self, owner, experiment, body):
        result = (
            await self.db.execute(
                select(Impression, Visit)
                .join(Visit, Impression.visit_id == Visit.id)
                .where(
                    Impression.id == body.impression_id,
                    Visit.member_id == owner,
                    Visit.experiment == experiment,
                )
            )
        ).one_or_none()
        if result is None:
            raise conflict()
        impression, visit = result
        candidate = self._candidate(visit, impression.candidate_id)
        if candidate is None:
            raise conflict()
        fields = dict(
            member_id=owner,
            session_id=visit.id,
            product_id=candidate.product_id,
            option_id=candidate.shade_id,
            surface=CART_SURFACE,
            event_type="cart_add",
            event_source="client",
            event_schema_version=CART_EVENT_SCHEMA,
            context_snapshot={
                "candidate_id": str(candidate.candidate_id),
                "impression_id": str(impression.id),
            },
        )
        inserted = await self.db.scalar(
            insert(Event)
            .values(event_id=body.event_id, occurred_at=datetime.now(UTC), **fields)
            .on_conflict_do_nothing()
            .returning(Event.event_id)
        )
        if inserted is None:
            existing = await self.db.get(Event, body.event_id)
            if existing is None or any(
                getattr(existing, key) != value for key, value in fields.items()
            ):
                raise conflict()
        await self.db.commit()

    async def performance(self, *, experiment, start, end, as_of, window_hours, owners, terms):
        return (
            (
                await self.db.execute(
                    text("""
                WITH visits AS (
                    SELECT v.*,
                        v.created_at + CAST(:window_hours AS int) * interval '1 hour' AS closes_at
                    FROM cart_recommendation_visits v JOIN members m ON m.id = v.member_id
                    WHERE v.experiment = :experiment
                      AND v.created_at >= :start AND v.created_at < :end AND v.created_at <= :as_of
                      AND m.terms_version = :terms AND m.id = ANY(CAST(:owners AS varchar[]))
                )
                SELECT v.arm, count(*) AS visits,
                    count(*) FILTER (WHERE mature) AS mature_visits,
                    count(*) FILTER (
                        WHERE mature AND jsonb_array_length(v.candidates) > 0
                    ) AS served_visits,
                    count(*) FILTER (WHERE mature AND EXISTS (
                        SELECT 1 FROM cart_recommendation_impressions i WHERE i.visit_id = v.id
                          AND i.occurred_at >= v.created_at AND i.occurred_at < v.closes_at
                    )) AS exposed_visits,
                    count(*) FILTER (WHERE mature AND EXISTS (
                        SELECT 1 FROM user_behavior_events e WHERE e.session_id = v.id
                          AND e.member_id = v.member_id AND e.surface = :surface
                          AND e.event_schema_version = :event_schema
                          AND e.event_type = 'cart_add' AND e.event_source = 'client'
                          AND e.occurred_at >= v.created_at AND e.occurred_at < v.closes_at
                    )) AS recommendation_add_visits,
                    count(*) FILTER (WHERE mature AND p.any_paid) AS paid_visits,
                    count(*) FILTER (WHERE mature AND p.new_product_paid)
                        AS new_product_paid_visits,
                    count(*) FILTER (WHERE mature AND p.recommendation_paid)
                        AS recommendation_paid_visits
                FROM visits v
                CROSS JOIN LATERAL (SELECT v.closes_at <= :as_of AS mature) w
                LEFT JOIN LATERAL (
                    SELECT count(o.id) > 0 AS any_paid,
                        bool_or(l.product_id IS NOT NULL AND NOT EXISTS (
                            SELECT 1 FROM jsonb_array_elements(v.basket) AS basket(item)
                            WHERE basket.item->>'product_id' = l.product_id
                        )) AS new_product_paid,
                        bool_or(l.cart_recommendation_event_id IS NOT NULL) AS recommendation_paid
                    FROM orders o LEFT JOIN order_lines l ON l.order_id = o.id
                    WHERE mature AND o.cart_visit_id = v.id AND o.user_id = v.member_id
                      AND o.status IN ('paid', 'preparing', 'shipped', 'delivered')
                      AND o.paid_at >= v.created_at AND o.paid_at < v.closes_at
                ) p ON true
                GROUP BY v.arm
            """),
                    dict(
                        experiment=experiment,
                        start=start,
                        end=end,
                        as_of=as_of,
                        window_hours=window_hours,
                        owners=sorted(owners),
                        terms=terms,
                        surface=CART_SURFACE,
                        event_schema=CART_EVENT_SCHEMA,
                    ),
                )
            )
            .mappings()
            .all()
        )
