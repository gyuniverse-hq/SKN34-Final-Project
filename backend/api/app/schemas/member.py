from datetime import datetime

from pydantic import BaseModel, Field

from app.core.auth import AuthUser
from app.schemas.base import ApiModel


class MemberRecord(BaseModel):
    id: str
    terms_version: str
    terms_agreed_at: datetime


class TermsStatus(ApiModel):
    version: str
    agreed_version: str | None
    agreed_at: datetime | None


class MeResponse(ApiModel):
    user: AuthUser
    terms: TermsStatus


class AgreeTermsRequest(ApiModel):
    version: str = Field(min_length=1, max_length=32)
