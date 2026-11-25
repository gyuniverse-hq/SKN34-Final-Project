from sqlalchemy import func, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.models.ar_personalization import (
    ArActivityEventRow as Event,
)
from app.models.ar_personalization import (
    ArRecommendationCandidateRow as Candidate,
)
from app.models.ar_personalization import (
    ArRecommendationImpressionRow as Impression,
)
from app.models.ar_personalization import (
    ArRecommendationRequestRow as Request,
)
from app.models.catalog import ProductRow, ShadeRow
from app.models.member import MemberRow
from app.schemas import ar_history as schema


def conflict():
    return ApiError(409, "AR history identity conflict", "ar_history_conflict")


class ArHistoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def access(self, owner: str, terms: str) -> tuple[bool, bool]:
        subscribed = await self.db.scalar(
            select(func.coalesce(MemberRow.skin_subscription_until > func.now(), False)).where(
                MemberRow.id == owner,
                MemberRow.terms_version == terms,
                MemberRow.ar_activity_consented_at.is_not(None),
            )
        )
        return subscribed is not None, bool(subscribed)

    async def lock_rank(self, request_id):
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"ar-palette:{request_id}"},
        )
        return await self.db.get(Request, request_id)

    async def rank_candidates(self, request_id):
        rows = await self.db.scalars(
            select(Candidate).where(Candidate.request_id == request_id).order_by(Candidate.rank)
        )
        return [
            schema.Candidate(
                candidate_id=r.candidate_id, product_id=r.product_id, shade_id=r.shade_id
            )
            for r in rows
        ]

    async def owned_server_rank(self, owner, zone, request_id):
        return await self.db.scalar(
            select(Request).where(
                Request.request_id == request_id,
                Request.member_id == owner,
                Request.makeup_zone == zone,
                Request.policy_version.startswith("ar1:"),
            )
        )

    async def ranking_inputs(self, owner, zone, at):
        ratings = await self.db.execute(
            text("""
                SELECT p.id, r.rating_avg, r.review_count
                FROM products p JOIN raw_oy_review_summary r
                  ON p.id = 'oy-' || lower(r.goods_no) AND r.is_latest
                WHERE p.makeup_zone = :zone AND p.texture IS NOT NULL
                  AND (r.collected_at IS NULL OR
                       r.collected_at <= CAST(:at AS timestamptz) AT TIME ZONE 'UTC')
                  AND r.rating_avg BETWEEN 1 AND 5 AND r.review_count > 0
                ORDER BY p.id
            """),
            {"zone": zone, "at": at},
        )
        shades = await self.db.execute(
            select(
                ShadeRow.product_id,
                ShadeRow.id,
                ShadeRow.hex,
                ProductRow.texture,
                ShadeRow.measure_method,
                ShadeRow.color_source,
            )
            .join(ProductRow)
            .where(ProductRow.makeup_zone == zone)
        )
        history = await self.db.execute(
            text("""
                SELECT product_id, shade_id, (occurred_at AT TIME ZONE 'Asia/Seoul')::date AS day,
                       max(CASE WHEN event_type = 'cart_add' THEN 3.0
                                WHEN impression_id IS NULL THEN 1.0 ELSE 0.7 END) AS weight
                FROM ar_activity_events
                WHERE member_id = :owner AND makeup_zone = :zone
                  AND occurred_at >= CAST(:at AS timestamptz) - interval '90 days'
                  AND occurred_at < :at AND received_at <= :at
                GROUP BY product_id, shade_id, day
                ORDER BY product_id, shade_id, day
            """),
            {"owner": owner, "zone": zone, "at": at},
        )
        return (
            {(p, s): (h, t, m, src) for p, s, h, t, m, src in shades},
            {p: (float(r), n) for p, r, n in ratings},
            [((p, s), d, float(w)) for p, s, d, w in history],
        )

    async def save_rank(
        self, body, owner, at, strategy, policy, candidates, *, cart_candidates=None
    ):
        self.db.add(
            Request(
                request_id=body.request_id,
                session_id=body.session_id,
                member_id=owner,
                makeup_zone=body.makeup_zone,
                created_at=at,
                strategy=strategy,
                policy_version=policy,
                cart_candidates=cart_candidates,
            )
        )
        await self.db.flush()
        self.db.add_all(
            Candidate(request_id=body.request_id, rank=i, **candidate.model_dump(by_alias=False))
            for i, candidate in enumerate(candidates, 1)
        )
        await self.db.commit()

    async def palette_inputs(self, owner: str, zone: str) -> schema.PaletteInputs:
        ratings = await self.db.execute(
            text("""
            SELECT p.id AS product_id, r.rating_avg AS rating, r.review_count AS reviews
            FROM products p JOIN raw_oy_review_summary r
              ON p.id = 'oy-' || lower(r.goods_no) AND r.is_latest
            WHERE p.makeup_zone = :zone AND p.texture IS NOT NULL
              AND r.rating_avg BETWEEN 1 AND 5 AND r.review_count > 0
        """),
            {"zone": zone},
        )
        # A dozen taps on the same shade in one day count once. A cart addition wins that day.
        preferences = await self.db.execute(
            text("""
            WITH daily AS (
                SELECT product_id, shade_id, (occurred_at AT TIME ZONE 'Asia/Seoul')::date AS day,
                       max(CASE WHEN event_type = 'cart_add' THEN 3.0
                                WHEN impression_id IS NULL THEN 1.0 ELSE 0.7 END) AS weight
                FROM ar_activity_events
                WHERE member_id = :owner AND makeup_zone = :zone
                  AND occurred_at BETWEEN statement_timestamp() - interval '90 days'
                                      AND statement_timestamp()
                GROUP BY product_id, shade_id, day
            )
            SELECT product_id, shade_id, sum(weight) AS weight FROM daily
            GROUP BY product_id, shade_id
            ORDER BY sum(weight) DESC, max(day) DESC, product_id, shade_id LIMIT 80
        """),
            {"owner": owner, "zone": zone},
        )
        return schema.PaletteInputs(
            ratings=[schema.ProductRating(**r) for r in ratings.mappings()],
            preferences=[schema.ShadePreference(**p) for p in preferences.mappings()],
        )

    async def _check_shades(self, zone: str, pairs: set[tuple[str, str]]):
        if not pairs:
            return
        found = await self.db.execute(
            select(ShadeRow.product_id, ShadeRow.id)
            .join(ProductRow)
            .where(
                ProductRow.makeup_zone == zone, tuple_(ShadeRow.product_id, ShadeRow.id).in_(pairs)
            )
        )
        if set(found) != pairs:
            raise ApiError(400, "Unknown shade or makeup zone", "invalid_ar_shade")

    async def _insert_once(self, model, key: str, values: dict):
        result = await self.db.scalar(
            insert(model).values(**values).on_conflict_do_nothing().returning(getattr(model, key))
        )
        if result is not None:
            return True
        existing = await self.db.get(model, values[key])
        if existing is None or any(getattr(existing, k) != v for k, v in values.items()):
            raise conflict()
        return False

    async def request(self, owner: str, body: schema.PaletteRequest):
        rows = [
            dict(request_id=body.request_id, rank=i, **c.model_dump(by_alias=False))
            for i, c in enumerate(body.candidates, 1)
        ]
        first_picks = body.direction in ("rating", "personalized")
        created = await self._insert_once(
            Request,
            "request_id",
            dict(
                request_id=body.request_id,
                session_id=body.session_id,
                member_id=owner,
                makeup_zone=body.makeup_zone,
                strategy=body.direction if first_picks else "nearby_" + body.direction,
                policy_version="palette-content-v1" if first_picks else "nearby-color-v1",
            ),
        )
        if created and rows:
            await self._check_shades(
                body.makeup_zone, {(c.product_id, c.shade_id) for c in body.candidates}
            )
            inserted = await self.db.scalars(
                insert(Candidate)
                .values(rows)
                .on_conflict_do_nothing()
                .returning(Candidate.candidate_id)
            )
            if len(inserted.all()) != len(rows):
                raise conflict()
        elif not created:
            saved = (
                await self.db.scalars(
                    select(Candidate)
                    .where(Candidate.request_id == body.request_id)
                    .order_by(Candidate.rank)
                )
            ).all()
            if len(saved) != len(rows) or any(
                any(getattr(s, k) != v for k, v in r.items())
                for s, r in zip(saved, rows, strict=True)
            ):
                raise conflict()
        await self.db.commit()

    async def impression(self, owner: str, body: schema.Impression):
        match = await self.db.scalar(
            select(Candidate.candidate_id)
            .join(Request)
            .where(
                Candidate.candidate_id == body.candidate_id,
                Request.member_id == owner,
            )
        )
        if match is None:
            raise ApiError(404, "Unknown AR candidate", "unknown_ar_candidate")
        await self._insert_once(Impression, "impression_id", body.model_dump(by_alias=False))
        await self.db.commit()

    async def event(self, owner: str, body: schema.Activity):
        if body.impression_id is not None:
            match = await self.db.scalar(
                select(Impression.impression_id)
                .select_from(Impression)
                .join(Candidate)
                .join(Request)
                .where(
                    Impression.impression_id == body.impression_id,
                    Request.member_id == owner,
                    Request.session_id == body.session_id,
                    Request.makeup_zone == body.makeup_zone,
                    Candidate.product_id == body.product_id,
                    Candidate.shade_id == body.shade_id,
                )
            )
            if match is None:
                raise ApiError(404, "Unknown AR impression for this event", "unknown_ar_impression")
        else:
            await self._check_shades(body.makeup_zone, {(body.product_id, body.shade_id)})
        await self._insert_once(
            Event,
            "event_id",
            dict(
                **body.model_dump(by_alias=False), member_id=owner, schema_version="ar-activity-v1"
            ),
        )
        await self.db.commit()
