from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.auth import AuthUser
from app.schemas.base import ApiModel


class MemberRecord(BaseModel):
    id: str
    terms_version: str
    terms_agreed_at: datetime
    camera_features_consent: bool | None = None
    ar_activity_consented_at: datetime | None = None
    skin_trial_run: str | None = None
    skin_subscription_until: datetime | None = None


class SkinAccess(ApiModel):
    expires_at: datetime | None
    subscribed: bool
    trial_used: bool


class CompleteAnalysisRequest(ApiModel):
    run_id: str = Field(min_length=1, max_length=128)


class TermsStatus(ApiModel):
    camera_features_consent: bool | None
    version: str
    ar_activity_consent: bool
    agreed_version: str | None
    agreed_at: datetime | None


class MeResponse(ApiModel):
    user: AuthUser
    terms: TermsStatus


ConsentKind = Literal["arActivity", "cameraFeatures"]


class ServiceConsentRequest(ApiModel):
    kind: ConsentKind
    enabled: bool


class AgreeTermsRequest(ApiModel):
    camera_features_consent: bool | None = None
    ar_activity_consent: bool | None = None
    version: str = Field(min_length=1, max_length=32)
