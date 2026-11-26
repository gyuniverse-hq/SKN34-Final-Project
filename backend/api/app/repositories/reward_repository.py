from datetime import date, datetime
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.member import MemberRow
from app.models.order import OrderRow
from app.models.reward import RewardAttendanceRow as Attendance
from app.models.reward import RewardCouponRow as Coupon


class RewardRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def member(self, owner: str, *, writing: bool):
        # Serialize check-ins, including requests straddling midnight and subscription changes.
        return await self.session.scalar(
            select(MemberRow).where(MemberRow.id == owner).with_for_update(read=not writing)
        )

    async def stamp_counts(self, owner: str, day: date):
        spent = (
            select(func.coalesce(func.sum(Attendance.stamp_goal), 0))
            .select_from(Coupon)
            .join(Attendance)
            .where(Coupon.member_id == owner)
            .scalar_subquery()
        )
        return (
            await self.session.execute(
                select(
                    func.count(Attendance.member_id) - spent,
                    func.count(Attendance.member_id).filter(Attendance.attendance_date == day),
                ).where(Attendance.member_id == owner)
            )
        ).one()

    async def record(
        self, owner: str, day: date, goal: int, expiry: datetime | None, now: datetime
    ):
        self.session.add(Attendance(member_id=owner, attendance_date=day, stamp_goal=goal))
        await self.session.flush()
        if expiry:
            self.session.add(
                Coupon(member_id=owner, source_date=day, issued_at=now, expires_at=expiry)
            )
            await self.session.flush()

    async def coupons(self, owner: str):
        return (
            await self.session.execute(
                select(Coupon, OrderRow.id, OrderRow.status)
                .outerjoin(
                    OrderRow,
                    and_(OrderRow.reward_coupon_id == Coupon.id, OrderRow.status != "canceled"),
                )
                .where(Coupon.member_id == owner)
                .order_by(Coupon.issued_at.desc())
            )
        ).all()

    async def coupon(self, owner: str, coupon_id: UUID):
        return await self.session.scalar(
            select(Coupon)
            .where(Coupon.id == coupon_id, Coupon.member_id == owner)
            .with_for_update()
        )

    async def active_order(self, coupon_id: UUID):
        return await self.session.scalar(
            select(OrderRow.id).where(
                OrderRow.reward_coupon_id == coupon_id, OrderRow.status != "canceled"
            )
        )

    async def commit(self):
        await self.session.commit()
