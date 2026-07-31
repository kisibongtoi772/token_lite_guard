"""Configuration management using pydantic-settings."""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    # Database
    db_path: str = "./data/token_guard.db"

    # OpenAI
    openai_api_key: Optional[str] = None
    openai_base_url: str = "https://api.openai.com/v1"

    # Anthropic
    anthropic_api_key: Optional[str] = None
    anthropic_base_url: str = "https://api.anthropic.com/v1"

    # Security
    admin_secret: Optional[str] = None

    # Budget defaults
    default_budget_tokens: int = 100_000

    @field_validator("db_path")
    @classmethod
    def ensure_db_dir(cls, v: str) -> str:
        """Auto-create the parent directory for the DB file."""
        db_path = Path(v)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return v

    @property
    def db_url(self) -> str:
        """SQLAlchemy-compatible SQLite URL."""
        return f"sqlite+aiosqlite:///{self.db_path}"

    def get_real_api_key(self, provider: str) -> Optional[str]:
        """Return the real API key for a given provider."""
        mapping = {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
        }
        return mapping.get(provider.lower())

    def get_provider_base_url(self, provider: str) -> str:
        """Return the base URL for a given provider."""
        mapping = {
            "openai": self.openai_base_url,
            "anthropic": self.anthropic_base_url,
        }
        return mapping.get(provider.lower(), self.openai_base_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance — load once, use everywhere."""
    return Settings()
