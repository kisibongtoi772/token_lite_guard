"""SQLModel ORM models for token_lite_guard."""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class VirtualKey(SQLModel, table=True):
    """A virtual API key issued to an agent/user with a token budget."""

    __tablename__ = "virtual_keys"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, description="Human-readable label for this key")
    key_hash: str = Field(unique=True, index=True, description="The virtual key value (e.g. tlg-xxxxx)")
    provider: str = Field(default="openai", description="Target provider: openai | anthropic")
    budget_tokens: int = Field(default=100_000, description="Maximum tokens allowed (0 = unlimited)")
    used_tokens: int = Field(default=0, description="Tokens consumed so far")
    is_active: bool = Field(default=True, description="Whether this key is currently active")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reset_at: Optional[datetime] = Field(default=None, description="When the budget was last reset")
    notes: Optional[str] = Field(default=None, description="Optional notes about this key")

    @property
    def remaining_tokens(self) -> int:
        """How many tokens are left in the budget."""
        if self.budget_tokens == 0:
            return -1  # Unlimited
        return max(0, self.budget_tokens - self.used_tokens)

    @property
    def usage_percentage(self) -> float:
        """Percentage of budget consumed (0.0 - 100.0)."""
        if self.budget_tokens == 0:
            return 0.0
        return min(100.0, (self.used_tokens / self.budget_tokens) * 100)


class UsageLog(SQLModel, table=True):
    """Immutable log of each proxied request."""

    __tablename__ = "usage_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    virtual_key_id: Optional[int] = Field(default=None, foreign_key="virtual_keys.id", index=True)
    virtual_key_name: str = Field(default="", description="Snapshot of key name at log time")
    model: str = Field(description="Model name used (e.g. gpt-4o)")
    provider: str = Field(description="Provider: openai | anthropic")
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    estimated_cost_usd: float = Field(default=0.0, description="Estimated cost in USD")
    status: str = Field(default="success", description="success | error | blocked")
    error_message: Optional[str] = Field(default=None)
    latency_ms: Optional[int] = Field(default=None, description="End-to-end latency in ms")
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)


class ModelPricing(SQLModel, table=True):
    """Pricing table for cost estimation (USD per 1M tokens)."""

    __tablename__ = "model_pricing"

    id: Optional[int] = Field(default=None, primary_key=True)
    model_pattern: str = Field(unique=True, description="Model name or prefix pattern")
    provider: str = Field(description="openai | anthropic")
    input_cost_per_1m: float = Field(description="USD per 1M input tokens")
    output_cost_per_1m: float = Field(description="USD per 1M output tokens")
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---- Default pricing data to seed on startup ----
DEFAULT_PRICING = [
    # OpenAI
    {"model_pattern": "gpt-4o", "provider": "openai", "input_cost_per_1m": 2.50, "output_cost_per_1m": 10.00},
    {"model_pattern": "gpt-4o-mini", "provider": "openai", "input_cost_per_1m": 0.15, "output_cost_per_1m": 0.60},
    {"model_pattern": "gpt-4-turbo", "provider": "openai", "input_cost_per_1m": 10.00, "output_cost_per_1m": 30.00},
    {"model_pattern": "gpt-4", "provider": "openai", "input_cost_per_1m": 30.00, "output_cost_per_1m": 60.00},
    {"model_pattern": "gpt-3.5-turbo", "provider": "openai", "input_cost_per_1m": 0.50, "output_cost_per_1m": 1.50},
    {"model_pattern": "o1", "provider": "openai", "input_cost_per_1m": 15.00, "output_cost_per_1m": 60.00},
    {"model_pattern": "o1-mini", "provider": "openai", "input_cost_per_1m": 3.00, "output_cost_per_1m": 12.00},
    # Anthropic
    {"model_pattern": "claude-3-5-sonnet", "provider": "anthropic", "input_cost_per_1m": 3.00, "output_cost_per_1m": 15.00},
    {"model_pattern": "claude-3-5-haiku", "provider": "anthropic", "input_cost_per_1m": 0.80, "output_cost_per_1m": 4.00},
    {"model_pattern": "claude-3-opus", "provider": "anthropic", "input_cost_per_1m": 15.00, "output_cost_per_1m": 75.00},
    {"model_pattern": "claude-3-sonnet", "provider": "anthropic", "input_cost_per_1m": 3.00, "output_cost_per_1m": 15.00},
    {"model_pattern": "claude-3-haiku", "provider": "anthropic", "input_cost_per_1m": 0.25, "output_cost_per_1m": 1.25},
]
