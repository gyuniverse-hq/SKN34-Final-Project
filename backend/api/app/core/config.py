from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    admin_enabled: bool = False
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://vishue:vishue@localhost:5432/vishue_db"
    redis_url: str | None = None
    catalog_cache_seconds: int = 300
    g5_enabled: bool = False
    g5_allow_local_sources: bool = False
    g5_openai_api_key: str | None = None
    g5_internal_token: str | None = None
    skincare_refresh_enabled: bool | None = None
    skincare_refresh_interval_seconds: int = 60
    ingredient_mapping_path: str | None = None
    ingredient_alias_approvals_path: str | None = None
    skin_recommendation_feedback_consented_members: set[str] = Field(default_factory=set)
    ar_palette_mode: Literal["legacy", "collect", "model", "experiment"] = "legacy"
    ar_palette_data_dir: Path = PROJECT_ROOT / "ml/data/ar-recommendation"
    ar_palette_model_dir: Path | None = None
    ar_palette_baseline_model_dir: Path | None = None
    ar_palette_experiment: str = Field(default="", pattern=r"^([a-z0-9-]{1,16})?$")
    cart_recommendation_experiment: str = Field(default="", pattern=r"^([a-z0-9-]{1,16})?$")
    # External APIs. Unset keys disable the matching feature instead of failing requests.
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    youtube_api_key: str | None = None
    # Only the recipe batch (app/jobs/extract_look_recipe.py) uses Gemini; the app never calls it.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"
    tutorial_searches_per_minute: int = 20
    offer_searches_per_minute: int = 20
    # Initial safety budgets, not measured throughput/SLA; tune after isolated G4 runs.
    option_searches_per_minute: int = Field(default=20, ge=1, le=120)
    option_search_product_limit: int = Field(default=42, ge=1, le=42)
    option_search_work_limit: int = Field(default=42, ge=1, le=42)
    option_search_timeout_seconds: float = Field(default=15, gt=0, le=15)
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
    # OpenAI-compatible vision LLM for admin lip naturalness (Astra). Keys stay server-only.
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str | None = None
    astra_model: str | None = None
    llm_timeout_seconds: float = 60
    # Temporary face refs for lip product-panel eval (eval period only; ADR-0013 exception).
    admin_lip_eval_dir: Path = PROJECT_ROOT / "runtime" / "lip-eval"
    # Admin Ops: in-cluster chatbot base (e.g. http://vishue-chatbot:8000). Empty skips probe.
    chatbot_base_url: str | None = None

    @property
    def g5_local_mode(self) -> bool:
        return self.g5_allow_local_sources and self.env == "local"

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
