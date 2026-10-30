"""Requirements for the standardized Olive Young category of a catalog product."""

from sqlalchemy import Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class OyCatalogCategoryRuleRow(Base):
    __tablename__ = "oy_catalog_category_rule"

    std_category_code: Mapped[str] = mapped_column(Text, primary_key=True)
    requires_texture: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_color: Mapped[bool] = mapped_column(Boolean, nullable=False)
