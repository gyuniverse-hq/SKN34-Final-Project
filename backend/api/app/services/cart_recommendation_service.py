import logging
from datetime import UTC, datetime
from itertools import zip_longest
from uuid import uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ar_palette import ranked_products, score_inputs, shade_features
from app.core.config import get_settings
from app.core.db import get_session, session_scope
from app.core.errors import ApiError
from app.repositories.ar_history_repository import ArHistoryRepository
from app.repositories.cart_recommendation_repository import CartRecommendationRepository, conflict
from app.schemas.cart_recommendation import CartRecommendationCandidate, CartRecommendations
from app.services.ar_history_service import ArHistoryService
from app.services.ar_palette_service import experiment_arm, score_palette
from app.services.member_service import TERMS_VERSION

ZONES = ("lip", "blush")
logger = logging.getLogger(__name__)


def shelf_order(by_zone, basket_zones):
    lip, blush = (by_zone[zone] for zone in ZONES)
    if basket_zones == {"lip"}:
        return blush[:3] + lip[:2]
    if basket_zones == {"blush"}:
        return lip[:3] + blush[:2]
    return [item for pair in zip_longest(lip, blush) for item in pair if item is not None][:5]


class CartRecommendationService:
    def __init__(self, repository, history, settings):
        self.repo = repository
        self.history = history
        self.settings = settings

    async def _enabled(self, owner):
        return bool(
            self.settings.cart_recommendation_experiment
        ) and await self.history.recommended(owner)

    async def visit(self, owner, body):
        if not await self._enabled(owner):
            return None
        experiment = self.settings.cart_recommendation_experiment
        existing = await self.repo.lock_visit(body.cart_visit_id)
        if existing is not None:
            if existing.member_id != owner or existing.experiment != experiment:
                raise conflict()
            return CartRecommendations(cart_visit_id=existing.id, candidates=existing.candidates)
        arm = experiment_arm(f"cart:{experiment}", owner)
        candidates = []
        if arm == "B":
            try:
                candidates = await self._recommend(owner, body)
            except ApiError as error:
                if error.code != "ar_experiment_unavailable":
                    raise
                logger.warning("Cart recommendations unavailable under the current AR policy")
        await self.repo.save_visit(
            owner,
            experiment,
            arm,
            body.cart_visit_id,
            [item.model_dump(by_alias=False) for item in body.items],
            candidates,
        )
        return CartRecommendations(cart_visit_id=body.cart_visit_id, candidates=candidates)

    async def _recommend(self, owner, body):
        excluded = {item.product_id for item in body.items}
        zones = {}
        colors = {zone: {} for zone in ZONES}
        for product, zone, shade, hex_value, texture, method, source in await self.repo.catalog(
            excluded
        ):
            zones[product] = zone
            if (
                zone in ZONES
                and shade
                and (color := shade_features(hex_value, texture, method, source))
            ):
                colors[zone][product, shade] = color
        basket_zones = {zones.get(product) for product in excluded} & set(ZONES)
        families = {zone: set() for zone in ZONES}
        for item in body.items:
            zone = zones.get(item.product_id)
            if zone in ZONES and (color := colors[zone].get((item.product_id, item.shade_id))):
                families[zone].add(color.family)
        now = datetime.now(UTC)
        by_zone = {}
        for zone, opposite in (("lip", "blush"), ("blush", "lip")):
            eligible = {
                key
                for key, color in colors[zone].items()
                if key[0] not in excluded
                and (not families[opposite] or color.family in families[opposite])
            }
            by_zone[zone] = (
                await self._rank_zone(
                    owner,
                    zone,
                    body.ar_request_ids.get(zone),
                    now,
                    colors[zone],
                    eligible,
                )
                if eligible
                else []
            )
        return [
            CartRecommendationCandidate(
                candidate_id=uuid4(),
                product_id=key[0],
                shade_id=key[1],
                makeup_zone=zone,
                position=position,
                original_rank=rank,
                policy_version=policy,
                ar_request_id=request_id,
            )
            for position, (zone, key, rank, policy, request_id) in enumerate(
                shelf_order(by_zone, basket_zones), 1
            )
        ]

    async def _rank_zone(self, owner, zone, request_id, now, catalog, eligible):
        ar = self.history.repo
        request = await ar.owned_server_rank(owner, zone, request_id) if request_id else None
        shown = await ar.rank_candidates(request_id) if request is not None else []
        excluded = {item.product_id for item in shown}
        start = len(shown) + 1
        if request is not None and request.cart_candidates:
            matches = [
                (zone, (product, shade), rank, request.policy_version, request_id)
                for rank, (product, shade) in enumerate(request.cart_candidates, start)
                if (product, shade) in eligible and product not in excluded
            ]
            if matches:
                return matches[:5]
        _, ratings, activity = await ar.ranking_inputs(owner, zone, now)
        rows, personalized = score_inputs(zone, sorted(eligible), catalog, ratings, activity)
        scores, _, policy = await score_palette(self.settings, owner, rows, personalized)
        result = []
        for rank, key in enumerate(ranked_products(rows, scores, excluded), start):
            result.append((zone, key, rank, policy, None))
            if len(result) == 5:
                break
        return result

    async def _require_enabled(self, owner):
        if not await self._enabled(owner):
            raise ApiError(403, "Cart recommendations are disabled", "cart_recommendation_disabled")

    async def impression(self, owner, body):
        await self._require_enabled(owner)
        return await self.repo.impression(owner, self.settings.cart_recommendation_experiment, body)

    async def cart_add(self, owner, body):
        await self._require_enabled(owner)
        await self.repo.cart_add(owner, self.settings.cart_recommendation_experiment, body)


def get_cart_recommendations(session: AsyncSession = Depends(get_session)):
    return CartRecommendationService(
        CartRecommendationRepository(session),
        ArHistoryService(ArHistoryRepository(session)),
        get_settings(),
    )


async def experiment_report(*, experiment, start, end, as_of, window_hours):
    async with session_scope() as session:
        rows = await CartRecommendationRepository(session).performance(
            experiment=experiment,
            start=start,
            end=end,
            as_of=as_of,
            window_hours=window_hours,
            owners=get_settings().ar_activity_consented_members,
            terms=TERMS_VERSION,
        )
    counts = (
        "visits",
        "mature_visits",
        "served_visits",
        "exposed_visits",
        "recommendation_add_visits",
        "paid_visits",
        "new_product_paid_visits",
        "recommendation_paid_visits",
    )
    arms = {arm: dict.fromkeys(counts, 0) for arm in ("A", "B")}
    for row in rows:
        arms[row["arm"]] = {key: row[key] for key in counts}
    for arm in arms.values():
        total = arm["mature_visits"]
        arm["pending_visits"] = arm["visits"] - total
        arm["new_product_paid_rate"] = arm["new_product_paid_visits"] / total if total else None
        arm["paid_rate"] = arm["paid_visits"] / total if total else None
    delta = {}
    for metric in ("new_product_paid_rate", "paid_rate"):
        a, b = (arms[arm][metric] for arm in ("A", "B"))
        delta[metric] = b - a if a is not None and b is not None else None
    return {
        "experiment": experiment,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "as_of": as_of.isoformat(),
        "purchase_window_hours": window_hours,
        "arms": arms,
        "rate_difference_b_minus_a": delta,
    }
