from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MemberRow(Base):
    """Backend record of a Supabase user. The account itself (email, password) stays in Supabase."""

    __tablename__ = "members"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_ar_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    camera_features_consent: Mapped[bool | None] = mapped_column()
    ar_activity_consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skin_trial_run: Mapped[str | None] = mapped_column(String(128))
    skin_subscription_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_version: Mapped[str] = mapped_column(String(32))
    terms_agreed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
