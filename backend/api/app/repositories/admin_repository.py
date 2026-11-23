from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.admin import AdminAuditLogRow, EvalRunRow, ProductAdminStateRow, StaffRoleRow
from app.models.catalog import ProductRow
from app.models.member import MemberRow
from app.models.order import OrderRow

CATALOG_LOCK = 7_284_732


class AdminRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @asynccontextmanager
    async def transaction(self):
        try:
            yield
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            raise

    async def catalog_lock(self):
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": CATALOG_LOCK}
        )

    async def role(self, user_id):
        return await self.session.get(StaffRoleRow, user_id)

    async def member_exists(self, user_id):
        return await self.session.get(MemberRow, user_id) is not None

    async def set_role(self, user_id, role):
        old = await self.role(user_id)
        if old:
            if role is None:
                await self.session.delete(old)
            else:
                old.role = role
        elif role:
            self.session.add(StaffRoleRow(user_id=user_id, role=role, created_by=None))

    def audit(self, actor, action, target_type, target_id, before, after, request_id):
        self.session.add(
            AdminAuditLogRow(
                actor_user_id=actor,
                action=action,
                target_type=target_type,
                target_id=target_id,
                before_json=before,
                after_json=after,
                request_id=request_id,
            )
        )

    async def audit_list(self, cursor, limit):
        stmt = select(AdminAuditLogRow)
        if cursor:
            stamp, ident = cursor
            stmt = stmt.where(
                tuple_(AdminAuditLogRow.created_at, AdminAuditLogRow.id) < (stamp, UUID(ident))
            )
        return list(
            await self.session.scalars(
                stmt.order_by(AdminAuditLogRow.created_at.desc(), AdminAuditLogRow.id.desc()).limit(
                    limit + 1
                )
            )
        )

    async def orders(self, status, cursor, limit):
        stamp = func.coalesce(OrderRow.created_at, datetime(1970, 1, 1, tzinfo=UTC))
        stmt = select(OrderRow)
        if status:
            stmt = stmt.where(OrderRow.status == status)
        if cursor:
            stmt = stmt.where(tuple_(stamp, OrderRow.id) < cursor)
        return list(
            await self.session.scalars(
                stmt.order_by(stamp.desc(), OrderRow.id.desc()).limit(limit + 1)
            )
        )

    async def order(self, ident, lock=False):
        stmt = select(OrderRow).options(selectinload(OrderRow.lines)).where(OrderRow.id == ident)
        if lock:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt.execution_options(populate_existing=True))

    async def products(self, query, category, cursor, limit):
        stmt = select(ProductRow)
        if query:
            stmt = stmt.where(ProductRow.search_text.contains(query.lower(), autoescape=True))
        if category:
            stmt = stmt.where(ProductRow.category == category)
        if cursor:
            stmt = stmt.where(ProductRow.id > cursor)
        return list(await self.session.scalars(stmt.order_by(ProductRow.id).limit(limit + 1)))

    async def product(self, ident, lock=False):
        stmt = select(ProductRow).where(ProductRow.id == ident)
        return await self.session.scalar(stmt.with_for_update() if lock else stmt)

    async def state(self, ident):
        return await self.session.get(ProductAdminStateRow, ident)

    def add(self, row):
        self.session.add(row)

    async def eval_by_hash(self, digest):
        return await self.session.scalar(
            select(EvalRunRow).where(EvalRunRow.summary_hash == digest)
        )

    async def eval_run(self, ident):
        return await self.session.get(EvalRunRow, ident)

    async def eval_runs(self, kind, limit):
        stmt = select(EvalRunRow)
        if kind:
            stmt = stmt.where(EvalRunRow.kind == kind)
        return list(
            await self.session.scalars(
                stmt.order_by(EvalRunRow.created_at.desc(), EvalRunRow.id.desc()).limit(limit)
            )
        )
