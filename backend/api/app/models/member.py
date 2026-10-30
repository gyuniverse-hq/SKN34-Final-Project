from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MemberRow(Base):
    """Backend record of a Supabase user. The account itself (email, password) stays in Supabase."""

    __tablename__ = "members"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    terms_version: Mapped[str] = mapped_column(String(32))
    terms_agreed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
