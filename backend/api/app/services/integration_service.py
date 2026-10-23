from app.clients.naver_client import get_naver_client
from app.clients.youtube_client import get_youtube_client
from app.schemas.external import Integrations


def get_integrations() -> Integrations:
    """Which optional external APIs have keys (shown by /api/health for deploy checks)."""
    return Integrations(
        youtube=get_youtube_client().configured,
        naver_shopping=get_naver_client().configured,
    )
