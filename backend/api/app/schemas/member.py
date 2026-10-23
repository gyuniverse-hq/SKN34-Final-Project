from app.core.auth import AuthUser
from app.schemas.base import ApiModel


class MeResponse(ApiModel):
    user: AuthUser
