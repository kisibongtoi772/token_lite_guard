"""Proxy router: intercept /v1/* requests, enforce budgets, forward upstream."""

import json
import logging
import time
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import get_settings
from ..database import get_engine
from ..models import ModelPricing, UsageLog, VirtualKey
from .forwarder import (
    build_upstream_url,
    detect_provider,
    forward_non_streaming,
    forward_streaming,
)
from .token_counter import count_messages_tokens, estimate_cost

logger = logging.getLogger(__name__)

router = APIRouter(tags=["proxy"])


# ─── Helpers ────────────────────────────────────────────────────────────────

def _extract_virtual_key(request: Request) -> str | None:
    """Extract the virtual key from Authorization header."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _error_response(status: int, message: str, code: str = "error") -> JSONResponse:
    """Return an OpenAI-compatible error JSON response."""
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "message": message,
                "type": "token_lite_guard_error",
                "code": code,
            }
        },
    )


async def _get_pricing(session: AsyncSession) -> list[dict]:
    """Load all pricing entries from DB."""
    result = await session.exec(select(ModelPricing))
    return [
        {
            "model_pattern": p.model_pattern,
            "input_cost_per_1m": p.input_cost_per_1m,
            "output_cost_per_1m": p.output_cost_per_1m,
        }
        for p in result.all()
    ]


async def _log_usage(
    virtual_key: VirtualKey | None,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    status: str,
    pricing_data: list[dict],
    latency_ms: int | None = None,
    error_message: str | None = None,
) -> None:
    """Write a usage log entry and deduct tokens from the virtual key budget."""
    engine = get_engine()
    total = input_tokens + output_tokens
    cost = estimate_cost(input_tokens, output_tokens, model, pricing_data)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        log = UsageLog(
            virtual_key_id=virtual_key.id if virtual_key else None,
            virtual_key_name=virtual_key.name if virtual_key else "unknown",
            model=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            estimated_cost_usd=cost,
            status=status,
            latency_ms=latency_ms,
            error_message=error_message,
        )
        session.add(log)

        # Deduct tokens from the virtual key
        if virtual_key and status == "success":
            result = await session.exec(
                select(VirtualKey).where(VirtualKey.id == virtual_key.id)
            )
            fresh_key = result.first()
            if fresh_key:
                fresh_key.used_tokens += total
                session.add(fresh_key)

        await session.commit()


# ─── Main Proxy Endpoint ─────────────────────────────────────────────────────

@router.api_route(
    "/v1/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
async def proxy(request: Request, path: str, background_tasks: BackgroundTasks):
    """
    The main proxy handler.
    1. Extract & validate virtual key
    2. Check budget
    3. Forward to upstream LLM
    4. Stream response back
    5. Deduct tokens in background
    """
    start_time = time.monotonic()
    settings = get_settings()

    # 1. Extract virtual key
    virtual_key_value = _extract_virtual_key(request)
    if not virtual_key_value:
        return _error_response(401, "Missing Authorization header with Bearer token.", "unauthorized")

    # 2. Lookup virtual key in DB
    engine = get_engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        result = await session.exec(
            select(VirtualKey).where(
                VirtualKey.key_hash == virtual_key_value,
                VirtualKey.is_active == True,
            )
        )
        virtual_key = result.first()

    if not virtual_key:
        return _error_response(401, "Invalid or inactive virtual API key.", "invalid_key")

    # 3. Read request body
    body = await request.body()
    model = "gpt-4o"
    is_streaming = False
    input_tokens = 0

    try:
        body_json = json.loads(body)
        model = body_json.get("model", "gpt-4o")
        is_streaming = body_json.get("stream", False)
        messages = body_json.get("messages", [])
        input_tokens = count_messages_tokens(messages, model)
    except (json.JSONDecodeError, Exception):
        pass

    provider = virtual_key.provider or detect_provider(model)

    # 4. Budget check
    if virtual_key.budget_tokens > 0:
        remaining = virtual_key.remaining_tokens
        if remaining <= 0:
            logger.warning(f"Budget exhausted for key '{virtual_key.name}' (id={virtual_key.id})")
            async with AsyncSession(engine, expire_on_commit=False) as session:
                pricing_data = await _get_pricing(session)
            background_tasks.add_task(
                _log_usage, virtual_key, model, provider,
                input_tokens, 0, "blocked", pricing_data,
            )
            return _error_response(
                429,
                f"Budget exhausted. Key '{virtual_key.name}' has used {virtual_key.used_tokens}/{virtual_key.budget_tokens} tokens.",
                "budget_exceeded",
            )

    # 5. Get real API key
    real_api_key = settings.get_real_api_key(provider)
    if not real_api_key:
        return _error_response(
            500,
            f"No real API key configured for provider '{provider}'. Set {provider.upper()}_API_KEY in .env",
            "provider_not_configured",
        )

    # 6. Build upstream URL
    upstream_url = build_upstream_url(provider, f"/v1/{path}")
    logger.info(f"Proxying {request.method} /v1/{path} → {upstream_url} [{model}]")

    # Load pricing for cost calculation
    async with AsyncSession(engine, expire_on_commit=False) as session:
        pricing_data = await _get_pricing(session)

    # 7. Forward the request
    if is_streaming:
        return await _handle_streaming(
            request=request,
            body=body,
            upstream_url=upstream_url,
            model=model,
            provider=provider,
            real_api_key=real_api_key,
            virtual_key=virtual_key,
            input_tokens=input_tokens,
            pricing_data=pricing_data,
            start_time=start_time,
            background_tasks=background_tasks,
        )
    else:
        return await _handle_non_streaming(
            request=request,
            body=body,
            upstream_url=upstream_url,
            model=model,
            provider=provider,
            real_api_key=real_api_key,
            virtual_key=virtual_key,
            input_tokens=input_tokens,
            pricing_data=pricing_data,
            start_time=start_time,
            background_tasks=background_tasks,
        )


async def _handle_streaming(
    request: Request,
    body: bytes,
    upstream_url: str,
    model: str,
    provider: str,
    real_api_key: str,
    virtual_key: VirtualKey,
    input_tokens: int,
    pricing_data: list[dict],
    start_time: float,
    background_tasks: BackgroundTasks,
) -> StreamingResponse:
    """Handle streaming response: yield chunks while counting output tokens."""
    total_output_tokens = 0

    async def generate():
        nonlocal total_output_tokens
        try:
            async for chunk, chunk_tokens in forward_streaming(
                url=upstream_url,
                method=request.method,
                headers=dict(request.headers),
                body=body,
                real_api_key=real_api_key,
                provider=provider,
            ):
                total_output_tokens += chunk_tokens
                yield chunk
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            error_payload = json.dumps({
                "error": {"message": str(e), "type": "proxy_error"}
            })
            yield f"data: {error_payload}\n\n".encode()
        finally:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            background_tasks.add_task(
                _log_usage,
                virtual_key, model, provider,
                input_tokens, total_output_tokens,
                "success", pricing_data, latency_ms,
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-TLG-Key": virtual_key.name,
        },
    )


async def _handle_non_streaming(
    request: Request,
    body: bytes,
    upstream_url: str,
    model: str,
    provider: str,
    real_api_key: str,
    virtual_key: VirtualKey,
    input_tokens: int,
    pricing_data: list[dict],
    start_time: float,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Handle non-streaming response."""
    try:
        status_code, resp_headers, resp_body = await forward_non_streaming(
            url=upstream_url,
            method=request.method,
            headers=dict(request.headers),
            body=body,
            real_api_key=real_api_key,
            provider=provider,
        )

        latency_ms = int((time.monotonic() - start_time) * 1000)

        # Extract actual token usage from response if available
        output_tokens = 0
        try:
            resp_json = json.loads(resp_body)
            usage = resp_json.get("usage", {})
            output_tokens = usage.get("completion_tokens", 0)
            if not input_tokens:
                input_tokens = usage.get("prompt_tokens", 0)
        except Exception:
            pass

        status = "success" if status_code < 400 else "error"
        background_tasks.add_task(
            _log_usage,
            virtual_key, model, provider,
            input_tokens, output_tokens,
            status, pricing_data, latency_ms,
        )

        # Build response, filtering out hop-by-hop headers
        safe_headers = {
            k: v for k, v in resp_headers.items()
            if k.lower() not in ("content-encoding", "transfer-encoding", "connection")
        }
        safe_headers["X-TLG-Key"] = virtual_key.name

        return JSONResponse(
            status_code=status_code,
            content=json.loads(resp_body) if resp_body else {},
            headers=safe_headers,
        )

    except Exception as e:
        logger.error(f"Non-streaming forward error: {e}")
        latency_ms = int((time.monotonic() - start_time) * 1000)
        background_tasks.add_task(
            _log_usage,
            virtual_key, model, provider,
            input_tokens, 0, "error", pricing_data, latency_ms, str(e),
        )
        return _error_response(502, f"Upstream error: {str(e)}", "upstream_error")
