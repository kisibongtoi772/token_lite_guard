"""SQLModel ORM models for token_lite_guard."""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class VirtualKey(SQLModel, table=True):
    """A virtual API key issued to an agent or user with an optional token budget."""

    __tablename__ = "virtual_keys"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, description="Human-readable label for this key")
    key_hash: str = Field(unique=True, index=True, description="The virtual key value (e.g. tlg-xxxxx)")
    provider: str = Field(default="openai", description="Target provider identifier")
    budget_tokens: int = Field(default=100_000, description="Maximum tokens allowed (0 = unlimited)")
    used_tokens: int = Field(default=0, description="Tokens consumed so far")
    is_active: bool = Field(default=True, description="Whether this key accepts requests")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reset_at: Optional[datetime] = Field(default=None, description="Timestamp of last budget reset")
    notes: Optional[str] = Field(default=None, description="Optional notes or description")

    @property
    def remaining_tokens(self) -> int:
        """Remaining token budget. Returns -1 for unlimited keys."""
        if self.budget_tokens == 0:
            return -1
        return max(0, self.budget_tokens - self.used_tokens)

    @property
    def usage_percentage(self) -> float:
        """Percentage of budget consumed (0.0 to 100.0)."""
        if self.budget_tokens == 0:
            return 0.0
        return min(100.0, (self.used_tokens / self.budget_tokens) * 100)


class UsageLog(SQLModel, table=True):
    """Immutable record of a proxied request."""

    __tablename__ = "usage_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    virtual_key_id: Optional[int] = Field(default=None, foreign_key="virtual_keys.id", index=True)
    virtual_key_name: str = Field(default="", description="Key name snapshot at log time")
    model: str = Field(description="Model identifier used (e.g. gpt-4o)")
    provider: str = Field(description="Provider identifier (e.g. openai, anthropic)")
    input_tokens: int = Field(default=0, description="Prompt / input token count")
    output_tokens: int = Field(default=0, description="Completion / output token count")
    total_tokens: int = Field(default=0, description="Total tokens for this request")
    estimated_cost_usd: float = Field(default=0.0, description="Estimated cost in USD")
    status: str = Field(default="success", description="success | error | blocked")
    error_message: Optional[str] = Field(default=None)
    latency_ms: Optional[int] = Field(default=None, description="End-to-end latency in milliseconds")
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)


class ModelPricing(SQLModel, table=True):
    """Pricing reference table for cost estimation (USD per 1M tokens)."""

    __tablename__ = "model_pricing"

    id: Optional[int] = Field(default=None, primary_key=True)
    model_pattern: str = Field(unique=True, description="Model name or prefix to match against")
    provider: str = Field(description="Provider identifier")
    input_cost_per_1m: float = Field(description="USD cost per 1 million input tokens")
    output_cost_per_1m: float = Field(description="USD cost per 1 million output tokens")
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CustomProvider(SQLModel, table=True):
    """
    User-defined custom provider.

    Allows forwarding requests to any OpenAI-compatible endpoint,
    such as self-hosted models, proxy services, or third-party APIs.
    """

    __tablename__ = "custom_providers"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True, description="Unique identifier slug (e.g. my-vllm)")
    display_name: str = Field(description="Human-readable display name")
    base_url: str = Field(description="Base URL of the OpenAI-compatible endpoint")
    api_key: Optional[str] = Field(default=None, description="API key (stored in plain text for localhost use)")
    auth_style: str = Field(default="bearer", description="bearer | x-api-key | api-key | none")
    description: Optional[str] = Field(default=None, description="Optional notes about this provider")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Optional pricing override for cost estimation
    input_cost_per_1m: Optional[float] = Field(default=None, description="Override: input cost per 1M tokens")
    output_cost_per_1m: Optional[float] = Field(default=None, description="Override: output cost per 1M tokens")


# ---------------------------------------------------------------------------
# Default pricing seed data
# Sources: provider pricing pages (approximate, subject to change)
# ---------------------------------------------------------------------------
DEFAULT_PRICING: list[dict] = [
    # OpenAI
    {"model_pattern": "gpt-4o",              "provider": "openai",    "input_cost_per_1m": 2.50,   "output_cost_per_1m": 10.00},
    {"model_pattern": "gpt-4o-mini",          "provider": "openai",    "input_cost_per_1m": 0.15,   "output_cost_per_1m": 0.60},
    {"model_pattern": "gpt-4-turbo",          "provider": "openai",    "input_cost_per_1m": 10.00,  "output_cost_per_1m": 30.00},
    {"model_pattern": "gpt-4",                "provider": "openai",    "input_cost_per_1m": 30.00,  "output_cost_per_1m": 60.00},
    {"model_pattern": "gpt-3.5-turbo",        "provider": "openai",    "input_cost_per_1m": 0.50,   "output_cost_per_1m": 1.50},
    {"model_pattern": "o1-pro",               "provider": "openai",    "input_cost_per_1m": 150.00, "output_cost_per_1m": 600.00},
    {"model_pattern": "o1",                   "provider": "openai",    "input_cost_per_1m": 15.00,  "output_cost_per_1m": 60.00},
    {"model_pattern": "o1-mini",              "provider": "openai",    "input_cost_per_1m": 3.00,   "output_cost_per_1m": 12.00},
    {"model_pattern": "o3",                   "provider": "openai",    "input_cost_per_1m": 10.00,  "output_cost_per_1m": 40.00},
    {"model_pattern": "o3-mini",              "provider": "openai",    "input_cost_per_1m": 1.10,   "output_cost_per_1m": 4.40},
    {"model_pattern": "o4-mini",              "provider": "openai",    "input_cost_per_1m": 1.10,   "output_cost_per_1m": 4.40},
    # Anthropic
    {"model_pattern": "claude-3-5-sonnet",    "provider": "anthropic", "input_cost_per_1m": 3.00,   "output_cost_per_1m": 15.00},
    {"model_pattern": "claude-3-5-haiku",     "provider": "anthropic", "input_cost_per_1m": 0.80,   "output_cost_per_1m": 4.00},
    {"model_pattern": "claude-3-7-sonnet",    "provider": "anthropic", "input_cost_per_1m": 3.00,   "output_cost_per_1m": 15.00},
    {"model_pattern": "claude-3-opus",        "provider": "anthropic", "input_cost_per_1m": 15.00,  "output_cost_per_1m": 75.00},
    {"model_pattern": "claude-3-sonnet",      "provider": "anthropic", "input_cost_per_1m": 3.00,   "output_cost_per_1m": 15.00},
    {"model_pattern": "claude-3-haiku",       "provider": "anthropic", "input_cost_per_1m": 0.25,   "output_cost_per_1m": 1.25},
    # Google Gemini
    {"model_pattern": "gemini-2.0-flash",     "provider": "google",    "input_cost_per_1m": 0.10,   "output_cost_per_1m": 0.40},
    {"model_pattern": "gemini-1.5-pro",       "provider": "google",    "input_cost_per_1m": 1.25,   "output_cost_per_1m": 5.00},
    {"model_pattern": "gemini-1.5-flash",     "provider": "google",    "input_cost_per_1m": 0.075,  "output_cost_per_1m": 0.30},
    {"model_pattern": "gemini-1.0-pro",       "provider": "google",    "input_cost_per_1m": 0.50,   "output_cost_per_1m": 1.50},
    # Mistral AI
    {"model_pattern": "mistral-large",        "provider": "mistral",   "input_cost_per_1m": 2.00,   "output_cost_per_1m": 6.00},
    {"model_pattern": "mistral-medium",       "provider": "mistral",   "input_cost_per_1m": 0.40,   "output_cost_per_1m": 2.00},
    {"model_pattern": "mistral-small",        "provider": "mistral",   "input_cost_per_1m": 0.20,   "output_cost_per_1m": 0.60},
    {"model_pattern": "codestral",            "provider": "mistral",   "input_cost_per_1m": 0.20,   "output_cost_per_1m": 0.60},
    {"model_pattern": "mixtral-8x7b",         "provider": "mistral",   "input_cost_per_1m": 0.70,   "output_cost_per_1m": 0.70},
    {"model_pattern": "mixtral-8x22b",        "provider": "mistral",   "input_cost_per_1m": 2.00,   "output_cost_per_1m": 6.00},
    # Groq
    {"model_pattern": "llama-3.3-70b",        "provider": "groq",      "input_cost_per_1m": 0.59,   "output_cost_per_1m": 0.79},
    {"model_pattern": "llama-3.1-8b-instant", "provider": "groq",      "input_cost_per_1m": 0.05,   "output_cost_per_1m": 0.08},
    {"model_pattern": "llama-3.2-1b",         "provider": "groq",      "input_cost_per_1m": 0.04,   "output_cost_per_1m": 0.04},
    {"model_pattern": "llama-3.2-3b",         "provider": "groq",      "input_cost_per_1m": 0.06,   "output_cost_per_1m": 0.06},
    {"model_pattern": "llama-3.2-90b",        "provider": "groq",      "input_cost_per_1m": 0.90,   "output_cost_per_1m": 0.90},
    {"model_pattern": "gemma2-9b",            "provider": "groq",      "input_cost_per_1m": 0.20,   "output_cost_per_1m": 0.20},
    # DeepSeek
    {"model_pattern": "deepseek-chat",        "provider": "deepseek",  "input_cost_per_1m": 0.27,   "output_cost_per_1m": 1.10},
    {"model_pattern": "deepseek-reasoner",    "provider": "deepseek",  "input_cost_per_1m": 0.55,   "output_cost_per_1m": 2.19},
    {"model_pattern": "deepseek-coder",       "provider": "deepseek",  "input_cost_per_1m": 0.14,   "output_cost_per_1m": 0.28},
    # Cohere
    {"model_pattern": "command-r-plus",       "provider": "cohere",    "input_cost_per_1m": 2.50,   "output_cost_per_1m": 10.00},
    {"model_pattern": "command-r",            "provider": "cohere",    "input_cost_per_1m": 0.15,   "output_cost_per_1m": 0.60},
    {"model_pattern": "command-light",        "provider": "cohere",    "input_cost_per_1m": 0.30,   "output_cost_per_1m": 0.60},
    # Together AI (popular open models)
    {"model_pattern": "meta-llama/Meta-Llama-3.1-70b", "provider": "together", "input_cost_per_1m": 0.88, "output_cost_per_1m": 0.88},
    {"model_pattern": "meta-llama/Meta-Llama-3.1-8b",  "provider": "together", "input_cost_per_1m": 0.18, "output_cost_per_1m": 0.18},
    # Ollama / LM Studio — free (local compute only)
    {"model_pattern": "ollama/",              "provider": "ollama",    "input_cost_per_1m": 0.0,    "output_cost_per_1m": 0.0},
    {"model_pattern": "lmstudio/",            "provider": "lmstudio",  "input_cost_per_1m": 0.0,    "output_cost_per_1m": 0.0},
]
