from datetime import UTC, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ApiError
from app.repositories.reward_repository import RewardRepository
from app.schemas.reward import RewardCoupon, RewardWallet

KST = timezone(timedelta(hours=9))


class RewardService:
    def __init__(self, repo: RewardRepository):
        self.repo = repo

    async def wallet(self, owner: str, *, attend: bool = False) -> RewardWallet:
        member = await self.repo.member(owner, writing=attend)
        if member is None:
            raise ApiError(409, "Membership registration is required", "terms_required")
        now = datetime.now(UTC)
        day = now.astimezone(KST).date()
        midnight = datetime.combine(day, time.min, KST)
        refresh = midnight + timedelta(days=1)
        goal = 7
        if member.skin_subscription_until and member.skin_subscription_until > now:
            goal = 4
            refresh = min(refresh, member.skin_subscription_until)
        stamps, checked = await self.repo.stamp_counts(owner, day)
        if attend and not checked:
            stamps += 1
            expiry = None
            if stamps >= goal:
                stamps -= goal
                expiry = midnight + timedelta(days=7)
            await self.repo.record(owner, day, goal, expiry, now)
            checked = True
        coupons = []
        for coupon, order_id, order_status in await self.repo.coupons(owner):
            if order_status == "pending":
                status = "reserved"
            elif order_status:
                status = "used"
            else:
                status = "available" if coupon.expires_at > now else "expired"
            coupons.append(
                RewardCoupon(
                    id=coupon.id,
                    expiresAt=coupon.expires_at,
                    status=status,
                    reservedOrderId=order_id if status == "reserved" else None,
                )
            )
        if attend:
            await self.repo.commit()
        return RewardWallet(
            stamps=stamps, goal=goal, checkedToday=bool(checked), refreshAt=refresh, coupons=coupons
        )

    async def discount(self, owner: str, coupon_id: UUID, subtotal: int) -> int:
        coupon = await self.repo.coupon(owner, coupon_id)
        if (
            not coupon
            or coupon.expires_at <= datetime.now(UTC)
            or subtotal < 10_000
            or await self.repo.active_order(coupon_id)
        ):
            raise ApiError(409, "Coupon is unavailable for this order", "coupon_unavailable")
        # The coupon row stays locked through creation of the pending order in the same session.
        return min(2000, subtotal // 10)


def get_reward_service(session: AsyncSession = Depends(get_session)) -> RewardService:
    return RewardService(RewardRepository(session))
