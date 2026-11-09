"""CosIng lookup evidence, ingredient functions, and user-defined concern links."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CosingFunctionRow(Base):
    __tablename__ = "cosing_function"

    function_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    function_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


class CosingIngredientLookupRow(Base):
    __tablename__ = "cosing_ingredient_lookup"
    __table_args__ = (
        CheckConstraint(
            "status IN ('accepted', 'accepted_no_functions', 'missing_english_name', "
            "'multiple_candidates', 'no_results', 'incomplete_response', 'name_mismatch', "
            "'wrong_source', 'missing_or_multiple_substance_id')",
            name="ck_cosing_lookup_status",
        ),
        CheckConstraint(
            "match_method IS NULL OR match_method IN ('exact', 'normalized')",
            name="ck_cosing_lookup_method",
        ),
    )

    ingredient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("raw_mfds_ingredient.ingredient_id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    match_method: Mapped[str | None] = mapped_column(Text)
    query_name: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    response_count: Mapped[int | None] = mapped_column(Integer)
    returned_inci: Mapped[list[str] | None] = mapped_column(JSONB)
    cosing_cas: Mapped[list[str] | None] = mapped_column(JSONB)
    substance_id: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngredientFunctionRow(Base):
    __tablename__ = "ingredient_function"
    __table_args__ = (Index("ix_ingredient_function_function_id", "function_id"),)

    ingredient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cosing_ingredient_lookup.ingredient_id"), primary_key=True
    )
    function_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cosing_function.function_id"), primary_key=True
    )


class FunctionConcernRow(Base):
    __tablename__ = "function_concern"
    __table_args__ = (Index("ix_function_concern_concern", "target_concern"),)

    function_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cosing_function.function_id"), primary_key=True
    )
    target_concern: Mapped[str] = mapped_column(
        Text, ForeignKey("rec_concern.target_concern"), primary_key=True
    )
