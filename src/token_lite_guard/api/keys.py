"""CRUD API for virtual keys management."""

import secrets
import string
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..database import get_session
from ..models import VirtualKey

router = APIRouter(prefix="/api/keys", tags=["keys"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Human-readable label")
    provider: str = Field(default="openai", description="openai | anthropic | auto")
    budget_tokens: int = Field(default=100_000, ge=0, description="Token budget (0 = unlimited)")
    notes: Optional[str] = Field(default=None, max_length=500)


class UpdateKeyRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    budget_tokens: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=500)


class KeyResponse(BaseModel):
    id: int
    name: str
    key_hash: str
    provider: str
    budget_tokens: int
    used_tokens: int
    remaining_tokens: int
    usage_percentage: float
    is_active: bool
    created_at: datetime
    reset_at: Optional[datetime]
    notes: Optional[str]

    @classmethod
    def from_model(cls, key: VirtualKey) -> "KeyResponse":
        return cls(
            id=key.id,
            name=key.name,
            key_hash=key.key_hash,
            provider=key.provider,
            budget_tokens=key.budget_tokens,
            used_tokens=key.used_tokens,
            remaining_tokens=key.remaining_tokens,
            usage_percentage=round(key.usage_percentage, 2),
            is_active=key.is_active,
            created_at=key.created_at,
            reset_at=key.reset_at,
            notes=key.notes,
        )


# ─── Key Generation ───────────────────────────────────────────────────────────

def _generate_virtual_key() -> str:
    """Generate a secure random virtual API key with tlg- prefix."""
    alphabet = string.ascii_letters + string.digits
    random_part = "".join(secrets.choice(alphabet) for _ in range(48))
    return f"tlg-{random_part}"


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("", response_model=KeyResponse, status_code=201)
async def create_key(
    body: CreateKeyRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new virtual API key with an optional token budget."""
    provider = body.provider.lower()
    if provider == "auto":
        provider = "openai"  # Default; will be auto-detected per-request

    key = VirtualKey(
        name=body.name,
        key_hash=_generate_virtual_key(),
        provider=provider,
        budget_tokens=body.budget_tokens,
        used_tokens=0,
        is_active=True,
        notes=body.notes,
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)

    return KeyResponse.from_model(key)


@router.get("", response_model=list[KeyResponse])
async def list_keys(
    active_only: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """List all virtual keys. Use ?active_only=true to filter inactive keys."""
    query = select(VirtualKey)
    if active_only:
        query = query.where(VirtualKey.is_active == True)
    query = query.order_by(VirtualKey.created_at.desc())

    result = await session.exec(query)
    keys = result.all()
    return [KeyResponse.from_model(k) for k in keys]


@router.get("/{key_id}", response_model=KeyResponse)
async def get_key(
    key_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get a single virtual key by ID."""
    result = await session.exec(select(VirtualKey).where(VirtualKey.id == key_id))
    key = result.first()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    return KeyResponse.from_model(key)


@router.put("/{key_id}", response_model=KeyResponse)
async def update_key(
    key_id: int,
    body: UpdateKeyRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a virtual key's name, budget, or active status."""
    result = await session.exec(select(VirtualKey).where(VirtualKey.id == key_id))
    key = result.first()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")

    if body.name is not None:
        key.name = body.name
    if body.budget_tokens is not None:
        key.budget_tokens = body.budget_tokens
    if body.is_active is not None:
        key.is_active = body.is_active
    if body.notes is not None:
        key.notes = body.notes

    session.add(key)
    await session.commit()
    await session.refresh(key)
    return KeyResponse.from_model(key)


@router.post("/{key_id}/reset", response_model=KeyResponse)
async def reset_key_budget(
    key_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Reset the used_tokens counter for a key back to 0."""
    result = await session.exec(select(VirtualKey).where(VirtualKey.id == key_id))
    key = result.first()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")

    key.used_tokens = 0
    key.reset_at = datetime.utcnow()
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return KeyResponse.from_model(key)


@router.delete("/{key_id}", status_code=204)
async def delete_key(
    key_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Permanently delete a virtual key."""
    result = await session.exec(select(VirtualKey).where(VirtualKey.id == key_id))
    key = result.first()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")

    await session.delete(key)
    await session.commit()
