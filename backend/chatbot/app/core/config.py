from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration from environment variables (or `.env` in local development)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"
    log_level: str = "INFO"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str | None = None
    redis_url: str | None = None
    # The api service owns PostgreSQL; the graph sync job reads the catalog over its HTTP API.
    catalog_api_url: str = "http://localhost:8000"
    # Any OpenAI-compatible Chat Completions endpoint. Unset key or model disables the chatbot.
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = 30
    chat_requests_per_minute: int = 10
    supabase_url: str | None = None
    supabase_publishable_key: str | None = None
    cors_origins: list[str] = []

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
