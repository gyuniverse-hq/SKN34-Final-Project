from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class OrderRow(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_created_at_id", "created_at", "id"),
        CheckConstraint("discount_krw BETWEEN 0 AND 2000", name="ck_orders_discount_krw"),
        Index(
            "ux_orders_active_reward_coupon",
            "reward_coupon_id",
            unique=True,
            postgresql_where=text("reward_coupon_id IS NOT NULL AND status <> 'canceled'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    amount_krw: Mapped[int] = mapped_column(Integer)
    order_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), index=True, default="pending")
    checkout_token_hash: Mapped[str] = mapped_column(String(64))
    payment_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cart_visit_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "cart_recommendation_visits.id", name="fk_orders_cart_visit", ondelete="SET NULL"
        ),
        index=True,
    )
    reward_coupon_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("reward_coupons.id", name="fk_orders_reward_coupon", ondelete="SET NULL")
    )
    discount_krw: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    lines: Mapped[list["OrderLineRow"]] = relationship(cascade="all, delete-orphan")


class OrderLineRow(Base):
    __tablename__ = "order_lines"
    __table_args__ = (
        CheckConstraint(
            "stock_debited IS NULL OR (stock_debited >= 0 AND stock_debited <= quantity)",
            name="ck_order_line_stock_debited",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str] = mapped_column(String(64))
    shade_id: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_krw: Mapped[int] = mapped_column(Integer)
    stock_debited: Mapped[int | None] = mapped_column(Integer)
    cart_recommendation_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "user_behavior_events.event_id",
            name="fk_order_lines_cart_recommendation_event",
            ondelete="SET NULL",
            use_alter=True,
        ),
        index=True,
    )
