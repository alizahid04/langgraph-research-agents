"""
Application configuration.

Loads settings from environment variables / .env file. There is no mock
mode: real research requires a real OPENROUTER_API_KEY and TAVILY_API_KEY.
If either is missing, agents raise a clear configuration error rather than
silently returning synthetic data (see app/exceptions.py).
"""
from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings, loaded once and cached."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM provider ---
    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/anthropic/claude-3.5-sonnet"

    # --- Search provider ---
    tavily_api_key: str = ""

    # --- Persistence ---
    database_url: str = "sqlite:///./research_platform.db"

    # --- Workflow ---
    max_revisions: int = 2

    # --- Misc ---
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000,http://localhost:8080,http://localhost:8000"

    @property
    def openrouter_configured(self) -> bool:
        """True when a real OpenRouter API key is set."""
        return bool(self.openrouter_api_key)

    @property
    def tavily_configured(self) -> bool:
        """True when a real Tavily API key is set."""
        return bool(self.tavily_api_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
