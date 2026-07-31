"""Statistics and analytics API for token usage."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..database import get_session
from ..models import UsageLog, VirtualKey

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview")
async def get_overview(session: AsyncSession = Depends(get_session)):
    """
    High-level dashboard stats:
    - Total tokens used (all time)
    - Total estimated cost (all time)
    - Requests today
    - Active keys count
    - Blocked requests today
    """
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # All-time totals
    total_result = await session.exec(
        select(
            func.coalesce(func.sum(UsageLog.total_tokens), 0),
            func.coalesce(func.sum(UsageLog.estimated_cost_usd), 0.0),
            func.count(UsageLog.id),
        )
    )
    total_tokens, total_cost, total_requests = total_result.one()

    # Today's requests
    today_result = await session.exec(
        select(
            func.count(UsageLog.id),
            func.coalesce(func.sum(UsageLog.total_tokens), 0),
        ).where(UsageLog.timestamp >= today_start)
    )
    requests_today, tokens_today = today_result.one()

    # Blocked today
    blocked_result = await session.exec(
        select(func.count(UsageLog.id)).where(
            UsageLog.timestamp >= today_start,
            UsageLog.status == "blocked",
        )
    )
    blocked_today = blocked_result.one()

    # Active keys
    active_keys_result = await session.exec(
        select(func.count(VirtualKey.id)).where(VirtualKey.is_active == True)
    )
    active_keys = active_keys_result.one()

    return {
        "total_tokens": int(total_tokens),
        "total_cost_usd": round(float(total_cost), 6),
        "total_requests": int(total_requests),
        "requests_today": int(requests_today),
        "tokens_today": int(tokens_today),
        "blocked_today": int(blocked_today),
        "active_keys": int(active_keys),
    }


@router.get("/usage-chart")
async def get_usage_chart(
    days: int = Query(default=7, ge=1, le=90, description="Number of days to chart"),
    session: AsyncSession = Depends(get_session),
):
    """
    Per-day token consumption for the last N days.
    Returns array of {date, tokens, cost, requests} objects.
    """
    since = datetime.utcnow() - timedelta(days=days)

    result = await session.exec(
        select(
            func.date(UsageLog.timestamp).label("date"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("tokens"),
            func.coalesce(func.sum(UsageLog.estimated_cost_usd), 0.0).label("cost"),
            func.count(UsageLog.id).label("requests"),
        )
        .where(UsageLog.timestamp >= since, UsageLog.status != "blocked")
        .group_by(func.date(UsageLog.timestamp))
        .order_by(func.date(UsageLog.timestamp))
    )

    rows = result.all()

    # Fill in missing days with zeros
    chart_data = []
    day_map = {str(r.date): r for r in rows}

    for i in range(days):
        date = (since + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        row = day_map.get(date)
        chart_data.append({
            "date": date,
            "tokens": int(row.tokens) if row else 0,
            "cost": round(float(row.cost), 6) if row else 0.0,
            "requests": int(row.requests) if row else 0,
        })

    return chart_data


@router.get("/by-model")
async def get_stats_by_model(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
):
    """Token usage breakdown by model."""
    since = datetime.utcnow() - timedelta(days=days)

    result = await session.exec(
        select(
            UsageLog.model,
            UsageLog.provider,
            func.coalesce(func.sum(UsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageLog.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(UsageLog.estimated_cost_usd), 0.0).label("cost"),
            func.count(UsageLog.id).label("requests"),
        )
        .where(UsageLog.timestamp >= since, UsageLog.status == "success")
        .group_by(UsageLog.model, UsageLog.provider)
        .order_by(func.sum(UsageLog.total_tokens).desc())
    )

    return [
        {
            "model": r.model,
            "provider": r.provider,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "total_tokens": int(r.total_tokens),
            "cost_usd": round(float(r.cost), 6),
            "requests": int(r.requests),
        }
        for r in result.all()
    ]


@router.get("/by-key")
async def get_stats_by_key(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
):
    """Token usage breakdown by virtual key."""
    since = datetime.utcnow() - timedelta(days=days)

    result = await session.exec(
        select(
            UsageLog.virtual_key_id,
            UsageLog.virtual_key_name,
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(UsageLog.estimated_cost_usd), 0.0).label("cost"),
            func.count(UsageLog.id).label("requests"),
        )
        .where(UsageLog.timestamp >= since)
        .group_by(UsageLog.virtual_key_id, UsageLog.virtual_key_name)
        .order_by(func.sum(UsageLog.total_tokens).desc())
    )

    return [
        {
            "key_id": r.virtual_key_id,
            "key_name": r.virtual_key_name,
            "total_tokens": int(r.total_tokens),
            "cost_usd": round(float(r.cost), 6),
            "requests": int(r.requests),
        }
        for r in result.all()
    ]


@router.get("/recent-logs")
async def get_recent_logs(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Return the most recent usage log entries."""
    result = await session.exec(
        select(UsageLog)
        .order_by(UsageLog.timestamp.desc())
        .limit(limit)
    )

    return [
        {
            "id": log.id,
            "key_name": log.virtual_key_name,
            "model": log.model,
            "provider": log.provider,
            "input_tokens": log.input_tokens,
            "output_tokens": log.output_tokens,
            "total_tokens": log.total_tokens,
            "cost_usd": log.estimated_cost_usd,
            "status": log.status,
            "latency_ms": log.latency_ms,
            "timestamp": log.timestamp.isoformat(),
        }
        for log in result.all()
    ]
