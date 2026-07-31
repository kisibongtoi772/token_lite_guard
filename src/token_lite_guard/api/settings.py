"""Key-value settings store for runtime configuration (API keys, etc.)."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..database import get_session, get_engine
from ..models import AppSetting

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Provider keys that can be configured via UI
PROVIDER_KEY_MAP = {
    "openai":     "OPENAI_API_KEY",
    "anthropic":  "ANTHROPIC_API_KEY",
    "google":     "GOOGLE_API_KEY",
    "mistral":    "MISTRAL_API_KEY",
    "groq":       "GROQ_API_KEY",
    "together":   "TOGETHER_API_KEY",
    "deepseek":   "DEEPSEEK_API_KEY",
    "cohere":     "COHERE_API_KEY",
    "azure":      "AZURE_OPENAI_API_KEY",
}

PROVIDER_URL_MAP = {
    "openai":    "OPENAI_BASE_URL",
    "anthropic": "ANTHROPIC_BASE_URL",
    "google":    "GOOGLE_BASE_URL",
    "mistral":   "MISTRAL_BASE_URL",
    "groq":      "GROQ_BASE_URL",
    "together":  "TOGETHER_BASE_URL",
    "deepseek":  "DEEPSEEK_BASE_URL",
    "cohere":    "COHERE_BASE_URL",
    "azure_endpoint": "AZURE_OPENAI_ENDPOINT",
    "ollama":    "OLLAMA_BASE_URL",
    "lmstudio":  "LM_STUDIO_BASE_URL",
}


async def get_setting(key: str, session: AsyncSession) -> Optional[str]:
    """Read a single setting from the database."""
    result = await session.exec(select(AppSetting).where(AppSetting.key == key))
    row = result.first()
    return row.value if row and row.value else None


async def get_setting_by_engine(key: str) -> Optional[str]:
    """Read a setting using a standalone session (for use in proxy)."""
    engine = get_engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await get_setting(key, session)


async def set_setting(key: str, value: str, session: AsyncSession) -> None:
    """Write or update a setting in the database."""
    result = await session.exec(select(AppSetting).where(AppSetting.key == key))
    row = result.first()
    if row:
        row.value = value
        row.updated_at = datetime.utcnow()
        session.add(row)
    else:
        session.add(AppSetting(key=key, value=value))
    await session.commit()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ProviderConfig(BaseModel):
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class SettingsResponse(BaseModel):
    providers: dict  # provider_id -> {api_key_set, base_url}
    general: dict    # PORT, DEFAULT_BUDGET_TOKENS, etc.


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def get_all_settings(session: AsyncSession = Depends(get_session)):
    """Return all configurable settings. API keys are masked."""
    from ..config import get_settings, BUILTIN_PROVIDERS
    env = get_settings()

    providers = {}
    for pid in BUILTIN_PROVIDERS:
        # DB takes priority, then env
        db_key_val = await get_setting(f"api_key:{pid}", session)
        db_url_val = await get_setting(f"base_url:{pid}", session)
        env_key = env.get_real_api_key(pid)
        env_url = env.get_provider_base_url(pid)

        effective_key = db_key_val or env_key or ""
        effective_url = db_url_val or env_url or ""

        providers[pid] = {
            "api_key_set": bool(effective_key),
            "api_key_source": "database" if db_key_val else ("env" if env_key else "none"),
            "base_url": effective_url,
            "base_url_source": "database" if db_url_val else "env",
        }

    return {
        "providers": providers,
        "general": {
            "port": env.port,
            "default_budget_tokens": env.default_budget_tokens,
        }
    }


@router.put("/provider/{provider_id}")
async def update_provider_settings(
    provider_id: str,
    body: ProviderConfig,
    session: AsyncSession = Depends(get_session),
):
    """Save a provider's API key and/or base URL to the database."""
    from ..config import BUILTIN_PROVIDERS
    if provider_id not in BUILTIN_PROVIDERS:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_id}")

    if body.api_key is not None:
        await set_setting(f"api_key:{provider_id}", body.api_key, session)
    if body.base_url is not None:
        await set_setting(f"base_url:{provider_id}", body.base_url, session)

    return {"status": "saved", "provider": provider_id}


@router.delete("/provider/{provider_id}/key")
async def clear_provider_key(
    provider_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Remove a provider API key from the database (reverts to .env value)."""
    await set_setting(f"api_key:{provider_id}", "", session)
    return {"status": "cleared", "provider": provider_id}
