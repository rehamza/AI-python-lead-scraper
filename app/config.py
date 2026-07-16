"""Application settings, loaded from .env / environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://localhost:5432/leadgen"

    # LLM
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"

    # Search providers
    search_provider_order: str = "serper,ddg,searxng,brave"
    serper_api_key: str = ""
    brave_api_key: str = ""
    searxng_url: str = ""

    # Email verification
    smtp_verify_enabled: bool = True
    smtp_helo_domain: str = "example.com"
    smtp_from_address: str = "verify@example.com"

    # Agent tuning
    agent_max_concurrent_searches: int = 4
    agent_max_concurrent_crawls: int = 8
    agent_qualify_batch_size: int = 10

    @property
    def provider_order(self) -> list[str]:
        return [p.strip().lower() for p in self.search_provider_order.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
