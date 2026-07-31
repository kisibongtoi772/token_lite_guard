"""Configuration management using pydantic-settings."""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Built-in provider identifiers and their default base URLs
BUILTIN_PROVIDERS: dict[str, dict] = {
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "auth_style": "bearer",
        "description": "OpenAI API — gpt-4o, gpt-4o-mini, o1, o3-mini",
    },
    "anthropic": {
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "auth_style": "x-api-key",
        "description": "Anthropic Claude — claude-3-5-sonnet, claude-3-5-haiku, claude-3-opus",
    },
    "google": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "auth_style": "bearer",
        "description": "Google Gemini — gemini-1.5-pro, gemini-1.5-flash, gemini-2.0-flash",
    },
    "mistral": {
        "name": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "auth_style": "bearer",
        "description": "Mistral AI — mistral-large, mistral-medium, codestral",
    },
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "auth_style": "bearer",
        "description": "Groq — llama-3.3-70b, llama-3.1-8b, mixtral-8x7b",
    },
    "together": {
        "name": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "auth_style": "bearer",
        "description": "Together AI — Llama, Mistral, Qwen, DBRX open models",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "auth_style": "bearer",
        "description": "DeepSeek — deepseek-chat, deepseek-coder, deepseek-reasoner",
    },
    "cohere": {
        "name": "Cohere",
        "base_url": "https://api.cohere.com/compatibility/v1",
        "auth_style": "bearer",
        "description": "Cohere — command-r-plus, command-r, command-light",
    },
    "azure": {
        "name": "Azure OpenAI",
        "base_url": "",  # Configured per-account via AZURE_OPENAI_ENDPOINT
        "auth_style": "api-key",
        "description": "Azure OpenAI Service — hosted OpenAI models on Azure",
    },
    "ollama": {
        "name": "Ollama (Local)",
        "base_url": "http://localhost:11434/v1",
        "auth_style": "bearer",
        "description": "Ollama local inference — llama3.2, qwen2.5, phi4, gemma3",
    },
    "lmstudio": {
        "name": "LM Studio (Local)",
        "base_url": "http://localhost:1234/v1",
        "auth_style": "bearer",
        "description": "LM Studio local server — any locally loaded model",
    },
}

# Model name prefix → provider mapping for auto-detection
MODEL_PROVIDER_MAP: list[tuple[str, str]] = [
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("text-davinci", "openai"),
    ("whisper", "openai"),
    ("claude", "anthropic"),
    ("gemini", "google"),
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
    ("codestral", "mistral"),
    ("llama", "groq"),          # Groq-hosted Llama (fallback; Together also hosts Llama)
    ("deepseek", "deepseek"),
    ("command", "cohere"),
    ("phi", "ollama"),
    ("gemma", "ollama"),
    ("qwen", "ollama"),
]


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

    # Google Gemini
    google_api_key: Optional[str] = None
    google_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"

    # Mistral AI
    mistral_api_key: Optional[str] = None
    mistral_base_url: str = "https://api.mistral.ai/v1"

    # Groq
    groq_api_key: Optional[str] = None
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Together AI
    together_api_key: Optional[str] = None
    together_base_url: str = "https://api.together.xyz/v1"

    # DeepSeek
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # Cohere
    cohere_api_key: Optional[str] = None
    cohere_base_url: str = "https://api.cohere.com/compatibility/v1"

    # Azure OpenAI
    azure_openai_api_key: Optional[str] = None
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-02-01"

    # Ollama (local)
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_api_key: str = "ollama"

    # LM Studio (local)
    lm_studio_base_url: str = "http://localhost:1234/v1"
    lm_studio_api_key: str = "lm-studio"

    # Security
    admin_secret: Optional[str] = None

    # Budget defaults
    default_budget_tokens: int = 100_000
    upstream_timeout_seconds: int = 120

    @field_validator("db_path")
    @classmethod
    def ensure_db_dir(cls, v: str) -> str:
        """Auto-create the parent directory for the DB file."""
        db_path = Path(v)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return v

    @property
    def db_url(self) -> str:
        """SQLAlchemy-compatible async SQLite URL."""
        return f"sqlite+aiosqlite:///{self.db_path}"

    def get_real_api_key(self, provider: str) -> Optional[str]:
        """Return the configured API key for a given built-in provider."""
        mapping: dict[str, Optional[str]] = {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "google": self.google_api_key,
            "mistral": self.mistral_api_key,
            "groq": self.groq_api_key,
            "together": self.together_api_key,
            "deepseek": self.deepseek_api_key,
            "cohere": self.cohere_api_key,
            "azure": self.azure_openai_api_key,
            "ollama": self.ollama_api_key or "ollama",
            "lmstudio": self.lm_studio_api_key or "lm-studio",
        }
        return mapping.get(provider.lower())

    def get_provider_base_url(self, provider: str) -> str:
        """Return the base URL for a given built-in provider."""
        mapping: dict[str, str] = {
            "openai": self.openai_base_url,
            "anthropic": self.anthropic_base_url,
            "google": self.google_base_url,
            "mistral": self.mistral_base_url,
            "groq": self.groq_base_url,
            "together": self.together_base_url,
            "deepseek": self.deepseek_base_url,
            "cohere": self.cohere_base_url,
            "azure": f"{self.azure_openai_endpoint}/openai" if self.azure_openai_endpoint else "",
            "ollama": self.ollama_base_url,
            "lmstudio": self.lm_studio_base_url,
        }
        return mapping.get(provider.lower(), self.openai_base_url)

    def get_auth_style(self, provider: str) -> str:
        """Return the authentication header style for a provider."""
        if provider == "anthropic":
            return "x-api-key"
        if provider == "azure":
            return "api-key"
        return "bearer"

    def is_provider_configured(self, provider: str) -> bool:
        """Return True if the provider has a non-empty API key configured."""
        local_providers = {"ollama", "lmstudio"}
        if provider in local_providers:
            return True
        key = self.get_real_api_key(provider)
        return bool(key and key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton — loaded once at startup."""
    return Settings()
