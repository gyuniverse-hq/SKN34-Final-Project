from sqlalchemy import text


class ArPaletteDatasetRepository:
    def __init__(self, session):
        self.session = session

    async def exposures(self, *, as_of, window, grace, members, terms):
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
                  AND m.terms_version = :terms AND r.member_id = ANY(CAST(:members AS text[]))
                  AND r.created_at <= :as_of AND i.received_at <= :as_of
                  AND i.occurred_at + CAST(:maturity AS interval) <= :as_of
                ORDER BY r.created_at, r.request_id, c.rank, i.impression_id
            """),
            {
                "as_of": as_of,
                "window": window,
                "maturity": window + grace,
                "members": sorted(members),
                "terms": terms,
            },
        )
        async for row in stream.mappings():
            yield row

    async def experiment_sessions(
        self, *, experiment, start, end, as_of, window, grace, members, terms
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
                      AND r.created_at + CAST(:maturity AS interval) <= :as_of
                      AND r.member_id = ANY(CAST(:members AS text[])) AND m.terms_version = :terms
                )
                SELECT r.member_id, r.session_id, r.arm,
                       bool_or(r.served = 'fallback') AS fallback,
                       bool_or(r.served = 'empty') AS empty,
                       array_agg(DISTINCT r.served)
                           FILTER (WHERE r.served LIKE 'm-%') AS model_versions,
                       COALESCE(bool_or(
                           a.event_type = 'cart_add'
                           AND a.member_id = r.member_id AND a.session_id = r.session_id
                           AND a.product_id = c.product_id AND a.shade_id = c.shade_id
                           AND a.makeup_zone = r.makeup_zone
                           AND a.occurred_at >= i.occurred_at
                           AND a.occurred_at <= i.occurred_at + CAST(:window AS interval)
                           AND a.received_at <= i.occurred_at + CAST(:maturity AS interval)
                       ), false) AS added_to_cart
                FROM decisions r
                LEFT JOIN ar_recommendation_candidates c ON c.request_id = r.request_id
                LEFT JOIN ar_recommendation_impressions i ON i.candidate_id = c.candidate_id
                  AND i.occurred_at + CAST(:maturity AS interval) <= :as_of
                  AND i.received_at <= :as_of
                LEFT JOIN ar_activity_events a ON a.impression_id = i.impression_id
                GROUP BY r.member_id, r.session_id, r.arm
            """),
            {
                "experiment": experiment,
                "start": start,
                "end": end,
                "as_of": as_of,
                "window": window,
                "maturity": window + grace,
                "members": sorted(members),
                "terms": terms,
            },
        )
        return result.mappings().all()
