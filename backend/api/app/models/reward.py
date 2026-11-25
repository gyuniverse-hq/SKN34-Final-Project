from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RewardAttendanceRow(Base):
    __tablename__ = "reward_attendance"
    __table_args__ = (
        CheckConstraint("stamp_goal IN (4, 7)", name="ck_reward_attendance_stamp_goal"),
    )

    member_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("members.id", name="fk_reward_attendance_member", ondelete="CASCADE"),
        primary_key=True,
    )
    attendance_date: Mapped[date] = mapped_column(Date, primary_key=True)
    stamp_goal: Mapped[int] = mapped_column(SmallInteger)


class RewardCouponRow(Base):
    __tablename__ = "reward_coupons"
    __table_args__ = (
        ForeignKeyConstraint(
            ["member_id", "source_date"],
            ["reward_attendance.member_id", "reward_attendance.attendance_date"],
            name="fk_reward_coupons_attendance",
            ondelete="CASCADE",
        ),
        UniqueConstraint("member_id", "source_date", name="uq_reward_coupons_attendance"),
        CheckConstraint("expires_at > issued_at", name="ck_reward_coupons_expiry"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    member_id: Mapped[str] = mapped_column(String(64))
    source_date: Mapped[date] = mapped_column(Date)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
