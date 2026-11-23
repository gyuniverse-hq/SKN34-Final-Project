import base64
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.toss_client import TossPaymentsClient
from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.core.observability import request_id_var
from app.models.admin import EvalRunRow, ProductAdminStateRow
from app.repositories.admin_repository import AdminRepository

TRANSITIONS = {
    "pending": (),
    "paid": ("preparing", "canceled"),
    "preparing": ("shipped", "canceled"),
    "shipped": ("delivered",),
    "delivered": (),
    "canceled": (),
}


def check_transition(old, new):
    if new not in TRANSITIONS.get(old, ()):
        raise ApiError(409, "Order transition is not allowed", "invalid_transition")


def encode_cursor(stamp, ident):
    return base64.urlsafe_b64encode(json.dumps([stamp.isoformat(), str(ident)]).encode()).decode()


def decode_cursor(value):
    if not value:
        return None
    try:
        stamp, ident = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        stamp = datetime.fromisoformat(stamp)
        if stamp.tzinfo is None or not isinstance(ident, str) or len(ident) > 128:
            raise ValueError
        return stamp, ident
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ApiError(400, "Invalid cursor", "invalid_cursor") from exc


def order_view(row):
    return {
        "id": row.id,
        "userId": row.user_id[:8] + "…",
        "amountKRW": row.amount_krw,
        "orderName": row.order_name,
        "status": row.status,
        "createdAt": row.created_at,
        "paidAt": row.paid_at,
        "paymentKey": (row.payment_key[:4] + "…") if row.payment_key else None,
        "nextStatuses": list(TRANSITIONS.get(row.status, ())),
    }


def eval_view(row):
    return {
        "id": str(row.id),
        "kind": row.kind,
        "createdAt": row.created_at,
        "rendererCommit": row.renderer_commit,
        "rendererDirty": row.renderer_dirty,
        "rubricVersion": row.rubric_version,
        "metricVersion": row.metric_version,
        "benchmarkSha256": row.benchmark_sha256,
        "summaryJson": row.summary_json,
    }


class AdminService:
    def __init__(self, repo, toss, cache):
        self.repo, self.toss, self.cache = repo, toss, cache

    def audit(self, actor, action, target_type, target_id, before, after):
        self.repo.audit(actor, action, target_type, target_id, before, after, request_id_var.get())

    async def audit_list(self, cursor, limit):
        decoded = decode_cursor(cursor)
        if decoded:
            try:
                UUID(decoded[1])
            except ValueError as exc:
                raise ApiError(400, "Invalid cursor", "invalid_cursor") from exc
        rows = await self.repo.audit_list(decoded, limit)
        return {
            "items": [
                {
                    "id": str(r.id),
                    "actorUserId": r.actor_user_id,
                    "action": r.action,
                    "targetType": r.target_type,
                    "targetId": r.target_id,
                    "beforeJson": r.before_json,
                    "afterJson": r.after_json,
                    "requestId": r.request_id,
                    "createdAt": r.created_at,
                }
                for r in rows[:limit]
            ],
            "nextCursor": encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id)
            if len(rows) > limit
            else None,
        }

    async def orders(self, status, cursor, limit):
        rows = await self.repo.orders(status, decode_cursor(cursor), limit)
        return {
            "items": [order_view(r) for r in rows[:limit]],
            "nextCursor": encode_cursor(
                rows[limit - 1].created_at or datetime(1970, 1, 1, tzinfo=UTC), rows[limit - 1].id
            )
            if len(rows) > limit
            else None,
        }

    async def order(self, ident):
        row = await self.repo.order(ident)
        if row is None:
            raise ApiError(404, "Order not found", "not_found")
        lines = []
        for line in row.lines:
            product = await self.repo.product(line.product_id)
            lines.append(
                {
                    "id": line.id,
                    "productId": line.product_id,
                    "productName": product.name_ko if product else line.product_id,
                    "shadeId": line.shade_id,
                    "quantity": line.quantity,
                    "unitPriceKRW": line.unit_price_krw,
                }
            )
        return {**order_view(row), "lines": lines}

    async def change_status(self, ident, body, actor):
        async with self.repo.transaction():
            await self.repo.catalog_lock()
            row = await self.repo.order(ident, lock=True)
            if row is None:
                raise ApiError(404, "Order not found", "not_found")
            check_transition(row.status, body.status)
            before = {"status": row.status}
            if body.status == "canceled":
                if not body.reason.strip():
                    raise ApiError(400, "A cancellation reason is required", "invalid_request")
                if row.payment_key:
                    await self.toss.cancel(row.payment_key, body.reason)
                for line in row.lines:
                    state = await self.repo.state(line.product_id)
                    if state and state.stock is not None and line.stock_debited:
                        stock_before = state.stock
                        state.stock += line.stock_debited
                        state.updated_at, state.updated_by = datetime.now(UTC), actor
                        self.audit(
                            actor,
                            "stock_restore",
                            "product",
                            line.product_id,
                            {"stock": stock_before},
                            {"stock": state.stock},
                        )
                    line.stock_debited = 0
            row.status = body.status
            # Reasons may contain personal data; record the state change, not free text.
            self.audit(actor, "order_status", "order", ident, before, {"status": row.status})
        return await self.order(ident)

    async def product_view(self, row, detail=False):
        state = await self.repo.state(row.id)
        result = {
            "id": row.id,
            "name": row.name_ko,
            "brand": row.brand,
            "category": row.category,
            "priceKRW": row.price_krw,
            "isVisible": state.is_visible if state else True,
            "stock": state.stock if state else None,
            "shadeCount": len(row.shades),
            "measurementMethods": sorted({s.measure_method or "unknown" for s in row.shades}),
        }
        if detail:
            result["shades"] = [
                {
                    "id": s.id,
                    "name": s.name,
                    "hex": s.hex,
                    "measureMethod": s.measure_method,
                    "colorSource": s.color_source,
                    "colorConfidence": s.color_confidence,
                }
                for s in row.shades
            ]
        return result

    async def products(self, query, category, cursor, limit):
        rows = await self.repo.products(query, category, cursor, limit)
        return {
            "items": [await self.product_view(r) for r in rows[:limit]],
            "nextCursor": rows[limit - 1].id if len(rows) > limit else None,
        }

    async def product(self, ident):
        row = await self.repo.product(ident)
        if row is None:
            raise ApiError(404, "Product not found", "not_found")
        return await self.product_view(row, detail=True)

    async def patch_product(self, ident, body, actor):
        async with self.repo.transaction():
            await self.repo.catalog_lock()
            row = await self.repo.product(ident, lock=True)
            if row is None:
                raise ApiError(404, "Product not found", "not_found")
            state = await self.repo.state(ident)
            before = {
                "isVisible": state.is_visible if state else True,
                "stock": state.stock if state else None,
            }
            if state is None:
                state = ProductAdminStateRow(product_id=ident, is_visible=True, stock=None)
                self.repo.add(state)
            for key in body.model_fields_set:
                setattr(state, key, getattr(body, key))
            state.updated_by, state.updated_at = actor, datetime.now(UTC)
            self.audit(
                actor,
                "product_state",
                "product",
                ident,
                before,
                {"isVisible": state.is_visible, "stock": state.stock},
            )
        await self.cache.delete_prefix("products:")
        await self.cache.delete_prefix("looks")
        return await self.product(ident)

    async def create_eval(self, body, actor):
        payload = body.model_dump(mode="json", by_alias=True)
        identity = {
            key: payload[key]
            for key in ("rendererCommit", "kind", "benchmarkSha256", "summaryJson")
        }
        digest = hashlib.sha256(
            json.dumps(
                identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            ).encode()
        ).hexdigest()
        async with self.repo.transaction():
            await self.repo.catalog_lock()
            existing = await self.repo.eval_by_hash(digest)
            if existing:
                return eval_view(existing)
            row = EvalRunRow(
                id=uuid4(),
                **body.model_dump(exclude={"summary_json"}),
                summary_json=payload["summaryJson"],
                summary_hash=digest,
                uploaded_by=actor,
                created_at=datetime.now(UTC),
            )
            self.repo.add(row)
            self.audit(actor, "eval_publish", "eval_run", str(row.id), None, {"kind": row.kind})
        return eval_view(row)

    async def eval_runs(self, kind, limit):
        return {"items": [eval_view(r) for r in await self.repo.eval_runs(kind, limit)]}

    async def eval_run(self, ident):
        row = await self.repo.eval_run(ident)
        if row is None:
            raise ApiError(404, "Evaluation not found", "not_found")
        return eval_view(row)


def get_admin_service(session: AsyncSession = Depends(get_session)):
    return AdminService(
        AdminRepository(session), TossPaymentsClient(get_settings().toss_secret_key), get_cache()
    )
