from datetime import datetime

from pydantic import BaseModel, Field

from app.core.auth import AuthUser
from app.schemas.base import ApiModel


class MemberRecord(BaseModel):
    id: str
    terms_version: str
    terms_agreed_at: datetime
    skin_trial_run: str | None = None
    skin_subscription_until: datetime | None = None


class SkinAccess(ApiModel):
    expires_at: datetime | None
    subscribed: bool
    trial_used: bool


class CompleteAnalysisRequest(ApiModel):
    run_id: str = Field(min_length=1, max_length=128)


class TermsStatus(ApiModel):
    version: str
    agreed_version: str | None
    agreed_at: datetime | None


class MeResponse(ApiModel):
    user: AuthUser
    terms: TermsStatus


class AgreeTermsRequest(ApiModel):
    version: str = Field(min_length=1, max_length=32)
