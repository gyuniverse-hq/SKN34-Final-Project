from sqlalchemy import text

from app.repositories.order_repository import (
    AR_CHECKOUT_SCHEMA,
    AR_CHECKOUT_SURFACE,
    AR_PURCHASE_KEY_PREFIX,
)


class ArPaletteDatasetRepository:
    def __init__(self, session):
        self.session = session

    async def exposures(self, *, as_of, window, grace, terms):
        stream = await self.session.stream(
            text("""
                SELECT r.request_id, r.member_id, r.session_id, r.makeup_zone,
                       r.created_at, r.policy_version, c.candidate_id, c.rank, i.impression_id,
                       EXISTS (
                           SELECT 1 FROM ar_activity_events a
                           WHERE a.impression_id = i.impression_id AND a.event_type = 'cart_add'
                             AND a.member_id = r.member_id AND a.session_id = r.session_id
                             AND a.product_id = c.product_id AND a.shade_id = c.shade_id
                             AND a.makeup_zone = r.makeup_zone
                             AND a.occurred_at >= i.occurred_at
                             AND a.occurred_at <= i.occurred_at + CAST(:window AS interval)
                             AND a.received_at <= i.occurred_at + CAST(:maturity AS interval)
                       ) AS added_to_cart
                FROM ar_recommendation_requests r
                JOIN members m ON m.id = r.member_id
                JOIN ar_recommendation_candidates c ON c.request_id = r.request_id
                JOIN ar_recommendation_impressions i ON i.candidate_id = c.candidate_id
                WHERE r.strategy IN ('rating', 'personalized', 'ml')
                  AND r.makeup_zone IN ('lip', 'blush')
                  AND split_part(r.policy_version, ':', 4) NOT LIKE 's-%'
                  AND m.terms_version = :terms AND r.created_at >= m.terms_agreed_at
                  AND r.created_at <= :as_of AND i.received_at <= :as_of
                  AND i.occurred_at + CAST(:maturity AS interval) <= :as_of
                ORDER BY r.created_at, r.request_id, c.rank, i.impression_id
            """),
            {
                "as_of": as_of,
                "window": window,
                "maturity": window + grace,
                "terms": terms,
            },
        )
        async for row in stream.mappings():
            yield row

    async def experiment_sessions(
        self, *, experiment, start, end, as_of, window, grace, terms, purchase_window=None
    ):
        result = await self.session.execute(
            text("""
                WITH decisions AS (
                    SELECT r.*, split_part(r.policy_version, ':', 3) AS arm,
                           split_part(r.policy_version, ':', 4) AS served
                    FROM ar_recommendation_requests r
                    JOIN members m ON m.id = r.member_id
                    WHERE split_part(r.policy_version, ':', 1) = 'ar1'
                      AND split_part(r.policy_version, ':', 2) = :experiment
                      AND split_part(r.policy_version, ':', 3) IN ('A', 'B')
                      AND r.created_at >= :start AND r.created_at < :end
                      AND r.created_at <= :as_of
                      AND r.created_at >= m.terms_agreed_at AND m.terms_version = :terms
                )
                SELECT r.member_id, r.session_id, r.arm,
                       bool_or(r.served = 'rule') AS served_rule,
                       bool_or(r.served = 'fallback') AS fallback,
                       bool_or(r.served = 'empty') AS empty,
                       array_agg(DISTINCT r.served) FILTER (
                           WHERE r.served LIKE 'm-%' OR r.served LIKE 's-%'
                       ) AS model_versions,
                       bool_or(a.event_id IS NOT NULL) AS added_to_cart,
                       bool_or(o.id IS NOT NULL) AS purchased,
                       greatest(max(r.created_at), max(i.occurred_at))
                           + CAST(:observation AS interval) <= :as_of AS mature
                FROM decisions r
                LEFT JOIN ar_recommendation_candidates c ON c.request_id = r.request_id
                LEFT JOIN ar_recommendation_impressions i ON i.candidate_id = c.candidate_id
                  AND i.received_at <= :as_of
                LEFT JOIN ar_activity_events a ON a.impression_id = i.impression_id
                  AND a.event_type = 'cart_add'
                  AND a.member_id = r.member_id AND a.session_id = r.session_id
                  AND a.product_id = c.product_id AND a.shade_id = c.shade_id
                  AND a.makeup_zone = r.makeup_zone
                  AND a.occurred_at >= i.occurred_at
                  AND a.occurred_at <= i.occurred_at + CAST(:window AS interval)
                  AND a.received_at <= i.occurred_at + CAST(:maturity AS interval)
                  AND a.received_at <= :as_of
                LEFT JOIN user_behavior_events p
                  ON p.source_record_key = :purchase_key_prefix || CAST(a.event_id AS text)
                  AND p.event_source = 'server' AND p.event_type = 'purchase_confirmed'
                  AND p.surface = :purchase_surface AND p.event_schema_version = :purchase_schema
                  AND p.member_id = r.member_id AND p.session_id = r.session_id
                  AND p.context_snapshot ->> 'ar_impression_id' = CAST(i.impression_id AS text)
                  AND p.occurred_at >= a.occurred_at
                  AND p.occurred_at <= i.occurred_at + CAST(:purchase_window AS interval)
                  AND p.occurred_at <= :as_of
                  AND p.received_at <= :as_of
                LEFT JOIN order_lines ol ON ol.id = p.order_line_id
                  AND ol.product_id = c.product_id AND ol.shade_id = c.shade_id
                LEFT JOIN orders o ON o.id = ol.order_id
                  AND o.user_id = r.member_id AND o.status = 'paid'
                GROUP BY r.member_id, r.session_id, r.arm
            """),
            {
                "experiment": experiment,
                "start": start,
                "end": end,
                "as_of": as_of,
                "window": window,
                "maturity": window + grace,
                "observation": max(window + grace, purchase_window or window),
                "purchase_window": purchase_window,
                "purchase_key_prefix": AR_PURCHASE_KEY_PREFIX,
                "purchase_surface": AR_CHECKOUT_SURFACE,
                "purchase_schema": AR_CHECKOUT_SCHEMA,
                "terms": terms,
            },
        )
        return result.mappings().all()
