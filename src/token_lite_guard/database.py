"""Database initialization, engine setup, and session management."""

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from .config import get_settings
from .models import ModelPricing, DEFAULT_PRICING

logger = logging.getLogger(__name__)

# Module-level engine — initialized once at startup
_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Return the global async engine (must call init_db first)."""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


async def init_db() -> None:
    """Create tables and seed default data. Call once at application startup."""
    global _engine
    settings = get_settings()

    logger.info(f"Initializing database at: {settings.db_path}")
    _engine = create_async_engine(
        settings.db_url,
        echo=False,  # Set True for SQL debug logging
        connect_args={
            "check_same_thread": False,
            "timeout": 30,
        },
    )

    # Create all tables defined in SQLModel
    async with _engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Seed pricing table if empty
    async with AsyncSession(_engine) as session:
        result = await session.exec(select(ModelPricing).limit(1))
        existing = result.first()
        if not existing:
            logger.info("Seeding default model pricing data...")
            for pricing_data in DEFAULT_PRICING:
                pricing = ModelPricing(**pricing_data)
                session.add(pricing)
            await session.commit()
            logger.info(f"Seeded {len(DEFAULT_PRICING)} model pricing entries.")

    logger.info("Database initialized successfully.")


async def close_db() -> None:
    """Dispose the engine on application shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
        logger.info("Database connection closed.")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session per request."""
    engine = get_engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
