from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SkincareServingRow(Base):
    __tablename__ = "skincare_serving"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_version: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSONB)
