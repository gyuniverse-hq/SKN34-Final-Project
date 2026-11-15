from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def model_project_root(api_root: Path) -> Path:
    # Source checkout: <repository>/backend/api. Docker ships only the API at /app.
    return (
        api_root.parent.parent
        if api_root.name == "api" and api_root.parent.name == "backend"
        else api_root
    )


PROJECT_ROOT = model_project_root(Path(__file__).resolve().parents[2])


class Settings(BaseSettings):
    """Runtime configuration from environment variables (or `.env` in local development)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://vishue:vishue@localhost:5432/vishue_db"
    redis_url: str | None = None
    catalog_cache_seconds: int = 300
    skincare_refresh_enabled: bool | None = None
    skincare_refresh_interval_seconds: int = 60
    ingredient_mapping_path: str | None = None
    ingredient_alias_approvals_path: str | None = None
    recommendation_comparison_enabled: bool = False
    recommendation_model: str = Field(
        default="recommend-cat-v3", pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    recommendation_models_dir: Path = PROJECT_ROOT / "ml/runs"
    recommendation_v1_url: str = "http://127.0.0.1:8080"
    recommendation_v1_revision: str | None = None
    # External APIs. Unset keys disable the matching feature instead of failing requests.
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    youtube_api_key: str | None = None
    # Only the recipe batch (app/jobs/extract_look_recipe.py) uses Gemini; the app never calls it.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"
    tutorial_searches_per_minute: int = 20
    offer_searches_per_minute: int = 20
    # Public Supabase values, used only to verify access tokens.
    supabase_url: str | None = None
    supabase_publishable_key: str | None = None
    # Server-only Supabase secret key, used only to delete accounts (ADR-0010).
    supabase_secret_key: str | None = None
    cors_origins: list[str] = []
    toss_client_key: str | None = None
    toss_secret_key: str | None = None
    payment_web_base_url: str | None = None
    payment_return_url: str = "kbeautyar://payment-result"

    @property
    def recommendation_bundle_path(self) -> Path:
        # Resolve relative roots against the repository, never the process working directory.
        root = self.recommendation_models_dir
        if not root.is_absolute():
            root = PROJECT_ROOT / root
        return root.resolve() / self.recommendation_model / "bundle"

    @property
    def recommendation_v2_bundle(self) -> str:
        """Local comparison scripts can still read the resolved path; selection is by name."""
        return str(self.recommendation_bundle_path)

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
