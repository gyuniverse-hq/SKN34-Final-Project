from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration from environment variables (or `.env` in local development)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://vishue:vishue@localhost:5432/vishue"
    redis_url: str | None = None
    catalog_cache_seconds: int = 300
    # External APIs. Unset keys disable the matching feature instead of failing requests.
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    youtube_api_key: str | None = None
    tutorial_searches_per_minute: int = 20
    offer_searches_per_minute: int = 20
    # Public Supabase values, used only to verify access tokens.
    supabase_url: str | None = None
    supabase_publishable_key: str | None = None
    cors_origins: list[str] = []
    toss_client_key: str | None = None
    toss_secret_key: str | None = None
    payment_web_base_url: str | None = None
    payment_return_url: str = "kbeautyar://payment-result"

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
