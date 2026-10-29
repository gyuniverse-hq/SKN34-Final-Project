from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class OrderRow(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    amount_krw: Mapped[int] = mapped_column(Integer)
    order_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), index=True, default="pending")
    checkout_token_hash: Mapped[str] = mapped_column(String(64))
    payment_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    lines: Mapped[list["OrderLineRow"]] = relationship(cascade="all, delete-orphan")


class OrderLineRow(Base):
    __tablename__ = "order_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str] = mapped_column(String(64))
    shade_id: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_krw: Mapped[int] = mapped_column(Integer)
