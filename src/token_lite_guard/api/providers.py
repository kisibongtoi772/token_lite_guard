"""CRUD API for managing custom providers and querying built-in provider status."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import BUILTIN_PROVIDERS, get_settings
from ..database import get_session
from ..models import CustomProvider

router = APIRouter(prefix="/api/providers", tags=["providers"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateProviderRequest(BaseModel):
    name: str = Field(
        ...,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9\-_]*$",
        description="Unique slug identifier (lowercase, hyphens/underscores allowed)",
    )
    display_name: str = Field(..., min_length=1, max_length=100)
    base_url: str = Field(..., description="Base URL of the OpenAI-compatible endpoint")
    api_key: Optional[str] = Field(default=None, description="API key (leave empty for open endpoints)")
    auth_style: str = Field(
        default="bearer",
        description="Authentication header style: bearer | x-api-key | api-key | none",
    )
    description: Optional[str] = Field(default=None, max_length=500)
    input_cost_per_1m: Optional[float] = Field(default=None, ge=0, description="USD per 1M input tokens")
    output_cost_per_1m: Optional[float] = Field(default=None, ge=0, description="USD per 1M output tokens")


class UpdateProviderRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    auth_style: Optional[str] = None
    description: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None
    input_cost_per_1m: Optional[float] = Field(default=None, ge=0)
    output_cost_per_1m: Optional[float] = Field(default=None, ge=0)


class ProviderResponse(BaseModel):
    id: int
    name: str
    display_name: str
    base_url: str
    auth_style: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    input_cost_per_1m: Optional[float]
    output_cost_per_1m: Optional[float]
    # API key is intentionally omitted from responses for security

    @classmethod
    def from_model(cls, p: CustomProvider) -> "ProviderResponse":
        return cls(
            id=p.id,
            name=p.name,
            display_name=p.display_name,
            base_url=p.base_url,
            auth_style=p.auth_style,
            description=p.description,
            is_active=p.is_active,
            created_at=p.created_at,
            input_cost_per_1m=p.input_cost_per_1m,
            output_cost_per_1m=p.output_cost_per_1m,
        )


class BuiltinProviderStatus(BaseModel):
    id: str
    name: str
    base_url: str
    auth_style: str
    description: str
    configured: bool


# ---------------------------------------------------------------------------
# Built-in provider status
# ---------------------------------------------------------------------------

@router.get("/builtin", response_model=list[BuiltinProviderStatus])
async def list_builtin_providers():
    """
    Return all built-in providers with their configuration status.

    A provider is considered 'configured' when its API key is present
    in the current .env file (or set as an environment variable).
    Local providers (Ollama, LM Studio) are always marked as configured.
    """
    settings = get_settings()
    return [
        BuiltinProviderStatus(
            id=provider_id,
            name=info["name"],
            base_url=info["base_url"],
            auth_style=info["auth_style"],
            description=info["description"],
            configured=settings.is_provider_configured(provider_id),
        )
        for provider_id, info in BUILTIN_PROVIDERS.items()
    ]


# ---------------------------------------------------------------------------
# Custom provider CRUD
# ---------------------------------------------------------------------------

@router.post("", response_model=ProviderResponse, status_code=201)
async def create_provider(
    body: CreateProviderRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Register a new custom provider.

    The `name` field becomes the provider identifier used when creating
    virtual keys (e.g. name="my-vllm" is used as provider="my-vllm").
    It must be unique and cannot conflict with built-in provider IDs.
    """
    if body.name in BUILTIN_PROVIDERS:
        raise HTTPException(
            status_code=409,
            detail=f"'{body.name}' is a reserved built-in provider ID. Choose a different name.",
        )

    # Check for duplicate
    existing = await session.exec(
        select(CustomProvider).where(CustomProvider.name == body.name)
    )
    if existing.first():
        raise HTTPException(status_code=409, detail=f"Provider '{body.name}' already exists.")

    provider = CustomProvider(
        name=body.name,
        display_name=body.display_name,
        base_url=body.base_url.rstrip("/"),
        api_key=body.api_key or None,
        auth_style=body.auth_style,
        description=body.description,
        input_cost_per_1m=body.input_cost_per_1m,
        output_cost_per_1m=body.output_cost_per_1m,
    )
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return ProviderResponse.from_model(provider)


@router.get("", response_model=list[ProviderResponse])
async def list_custom_providers(session: AsyncSession = Depends(get_session)):
    """List all user-defined custom providers."""
    result = await session.exec(
        select(CustomProvider).order_by(CustomProvider.created_at.desc())
    )
    return [ProviderResponse.from_model(p) for p in result.all()]


@router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(
    provider_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get a custom provider by ID."""
    result = await session.exec(
        select(CustomProvider).where(CustomProvider.id == provider_id)
    )
    provider = result.first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found.")
    return ProviderResponse.from_model(provider)


@router.put("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: int,
    body: UpdateProviderRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a custom provider's configuration."""
    result = await session.exec(
        select(CustomProvider).where(CustomProvider.id == provider_id)
    )
    provider = result.first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found.")

    if body.display_name is not None:
        provider.display_name = body.display_name
    if body.base_url is not None:
        provider.base_url = body.base_url.rstrip("/")
    if body.api_key is not None:
        provider.api_key = body.api_key or None
    if body.auth_style is not None:
        provider.auth_style = body.auth_style
    if body.description is not None:
        provider.description = body.description
    if body.is_active is not None:
        provider.is_active = body.is_active
    if body.input_cost_per_1m is not None:
        provider.input_cost_per_1m = body.input_cost_per_1m
    if body.output_cost_per_1m is not None:
        provider.output_cost_per_1m = body.output_cost_per_1m

    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return ProviderResponse.from_model(provider)


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Permanently delete a custom provider."""
    result = await session.exec(
        select(CustomProvider).where(CustomProvider.id == provider_id)
    )
    provider = result.first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found.")
    await session.delete(provider)
    await session.commit()


@router.post("/{provider_id}/test")
async def test_provider(
    provider_id: int,
    session: AsyncSession = Depends(get_session),
):
    """
    Test connectivity to a custom provider by calling its /models endpoint.
    Returns the HTTP status and a sample of the response body.
    """
    import httpx

    result = await session.exec(
        select(CustomProvider).where(CustomProvider.id == provider_id)
    )
    provider = result.first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found.")

    test_url = f"{provider.base_url.rstrip('/')}/models"
    headers: dict[str, str] = {}

    if provider.api_key and provider.auth_style == "bearer":
        headers["authorization"] = f"Bearer {provider.api_key}"
    elif provider.api_key and provider.auth_style == "x-api-key":
        headers["x-api-key"] = provider.api_key
    elif provider.api_key and provider.auth_style == "api-key":
        headers["api-key"] = provider.api_key

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(test_url, headers=headers)
        return {
            "success": response.status_code < 400,
            "status_code": response.status_code,
            "url": test_url,
            "response_preview": response.text[:500] if response.text else None,
        }
    except httpx.ConnectError:
        return {"success": False, "error": "Connection refused. Is the server running?", "url": test_url}
    except httpx.TimeoutException:
        return {"success": False, "error": "Connection timed out (10s).", "url": test_url}
    except Exception as exc:
        return {"success": False, "error": str(exc), "url": test_url}
