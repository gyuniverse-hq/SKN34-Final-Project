from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RewardCoupon(BaseModel):
    id: UUID
    expires_at: datetime = Field(alias="expiresAt")
    status: Literal["available", "reserved", "used", "expired"]
    reserved_order_id: str | None = Field(alias="reservedOrderId")


class RewardWallet(BaseModel):
    stamps: int
    goal: int
    checked_today: bool = Field(alias="checkedToday")
    refresh_at: datetime = Field(alias="refreshAt")
    coupons: list[RewardCoupon]
