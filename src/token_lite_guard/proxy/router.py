"""Proxy router: intercept /v1/* requests, enforce budgets, forward upstream."""

import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import get_settings
from ..database import get_engine
from ..models import CustomProvider, ModelPricing, UsageLog, VirtualKey
from .forwarder import (
    build_upstream_url,
    detect_provider,
    forward_non_streaming,
    forward_streaming,
)
from .token_counter import count_messages_tokens, estimate_cost

logger = logging.getLogger(__name__)

router = APIRouter(tags=["proxy"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_virtual_key(request: Request) -> Optional[str]:
    """Extract the Bearer token from the Authorization header."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _error_response(status: int, message: str, code: str = "error") -> JSONResponse:
    """Return an OpenAI-compatible error envelope."""
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
    """Fetch all pricing records from the database."""
    result = await session.exec(select(ModelPricing))
    return [
        {
            "model_pattern": p.model_pattern,
            "input_cost_per_1m": p.input_cost_per_1m,
            "output_cost_per_1m": p.output_cost_per_1m,
        }
        for p in result.all()
    ]


async def _resolve_custom_provider(
    provider_name: str,
    session: AsyncSession,
) -> Optional[CustomProvider]:
    """Look up a custom provider by name. Returns None for built-in providers."""
    result = await session.exec(
        select(CustomProvider).where(
            CustomProvider.name == provider_name,
            CustomProvider.is_active == True,
        )
    )
    return result.first()


async def _log_usage(
    virtual_key: Optional[VirtualKey],
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    status: str,
    pricing_data: list[dict],
    latency_ms: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """Write a usage log entry and deduct tokens from the virtual key."""
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

        if virtual_key and status == "success":
            result = await session.exec(
                select(VirtualKey).where(VirtualKey.id == virtual_key.id)
            )
            fresh_key = result.first()
            if fresh_key:
                fresh_key.used_tokens += total
                session.add(fresh_key)

        await session.commit()


# ---------------------------------------------------------------------------
# Main proxy endpoint
# ---------------------------------------------------------------------------

@router.api_route(
    "/v1/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
async def proxy(request: Request, path: str, background_tasks: BackgroundTasks):
    """
    Core proxy handler — 6-step pipeline:

    1. Extract virtual key from Authorization header
    2. Validate virtual key against database
    3. Enforce token budget (HTTP 429 on exhaustion)
    4. Resolve provider config (built-in or custom)
    5. Forward request to upstream LLM
    6. Stream response back, deduct tokens in background
    """
    start_time = time.monotonic()
    settings = get_settings()

    # Step 1 — extract virtual key
    virtual_key_value = _extract_virtual_key(request)
    if not virtual_key_value:
        return _error_response(401, "Missing Authorization header. Provide a virtual key as: Bearer <key>", "unauthorized")

    engine = get_engine()

    # Step 2 — validate virtual key
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

    # Step 3 — read request body and count input tokens
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
    except Exception:
        pass

    provider = virtual_key.provider or detect_provider(model)

    # Step 4 — budget enforcement
    if virtual_key.budget_tokens > 0 and virtual_key.remaining_tokens <= 0:
        logger.warning("Budget exhausted for key '%s' (id=%d)", virtual_key.name, virtual_key.id)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            pricing_data = await _get_pricing(session)
        background_tasks.add_task(
            _log_usage, virtual_key, model, provider,
            input_tokens, 0, "blocked", pricing_data,
        )
        return _error_response(
            429,
            f"Budget exhausted. Key '{virtual_key.name}' has consumed "
            f"{virtual_key.used_tokens:,} of {virtual_key.budget_tokens:,} tokens.",
            "budget_exceeded",
        )

    # Step 5 — resolve provider credentials and endpoint
    async with AsyncSession(engine, expire_on_commit=False) as session:
        pricing_data = await _get_pricing(session)
        custom_provider = await _resolve_custom_provider(provider, session)

    if custom_provider:
        real_api_key = custom_provider.api_key or "no-key"
        auth_style = custom_provider.auth_style
        upstream_url = build_upstream_url(provider, f"/v1/{path}", custom_base_url=custom_provider.base_url)
        extra_headers = None
    else:
        # Check database settings first (configured via UI), then fall back to .env
        from ..api.settings import get_setting_by_engine
        db_api_key = await get_setting_by_engine(f"api_key:{provider}")
        real_api_key = (db_api_key or settings.get_real_api_key(provider) or "").strip()
        auth_style = settings.get_auth_style(provider)
        extra_headers = None

        if not real_api_key:
            return _error_response(
                500,
                f"No API key configured for provider '{provider}'. "
                f"Add it in the dashboard under Settings, or set {provider.upper()}_API_KEY in your .env file.",
                "provider_not_configured",
            )

        # Check for DB base_url override
        db_base_url = await get_setting_by_engine(f"base_url:{provider}")
        if db_base_url:
            upstream_url = build_upstream_url(provider, f"/v1/{path}", custom_base_url=db_base_url)
        else:
            upstream_url = build_upstream_url(provider, f"/v1/{path}")

        # Azure requires additional query parameters
        if provider == "azure" and settings.azure_openai_api_version:
            upstream_url += f"?api-version={settings.azure_openai_api_version}"

    logger.info("Proxying %s /v1/%s -> %s [model=%s, key=%s]",
                request.method, path, upstream_url, model, virtual_key.name)

    # Step 6 — forward
    kwargs = dict(
        body=body,
        real_api_key=real_api_key,
        auth_style=auth_style,
        extra_headers=extra_headers,
    )

    if is_streaming:
        return await _handle_streaming(
            request, upstream_url, model, provider, virtual_key,
            input_tokens, pricing_data, start_time, background_tasks, **kwargs,
        )
    return await _handle_non_streaming(
        request, upstream_url, model, provider, virtual_key,
        input_tokens, pricing_data, start_time, background_tasks, **kwargs,
    )


# ---------------------------------------------------------------------------
# Response handlers
# ---------------------------------------------------------------------------

async def _handle_streaming(
    request: Request,
    upstream_url: str,
    model: str,
    provider: str,
    virtual_key: VirtualKey,
    input_tokens: int,
    pricing_data: list[dict],
    start_time: float,
    background_tasks: BackgroundTasks,
    body: bytes,
    real_api_key: str,
    auth_style: str,
    extra_headers,
) -> StreamingResponse:
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
                auth_style=auth_style,
                extra_headers=extra_headers,
            ):
                total_output_tokens += chunk_tokens
                yield chunk
        except Exception as exc:
            logger.error("Streaming error: %s", exc)
            error_payload = json.dumps({"error": {"message": str(exc), "type": "proxy_error"}})
            yield f"data: {error_payload}\n\n".encode()
        finally:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            background_tasks.add_task(
                _log_usage, virtual_key, model, provider,
                input_tokens, total_output_tokens, "success", pricing_data, latency_ms,
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-TLG-Virtual-Key": virtual_key.name,
        },
    )


async def _handle_non_streaming(
    request: Request,
    upstream_url: str,
    model: str,
    provider: str,
    virtual_key: VirtualKey,
    input_tokens: int,
    pricing_data: list[dict],
    start_time: float,
    background_tasks: BackgroundTasks,
    body: bytes,
    real_api_key: str,
    auth_style: str,
    extra_headers,
) -> JSONResponse:
    try:
        status_code, resp_headers, resp_body = await forward_non_streaming(
            url=upstream_url,
            method=request.method,
            headers=dict(request.headers),
            body=body,
            real_api_key=real_api_key,
            auth_style=auth_style,
            extra_headers=extra_headers,
        )
        latency_ms = int((time.monotonic() - start_time) * 1000)

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
            _log_usage, virtual_key, model, provider,
            input_tokens, output_tokens, status, pricing_data, latency_ms,
        )

        safe_headers = {
            k: v for k, v in resp_headers.items()
            if k.lower() not in ("content-encoding", "transfer-encoding", "connection")
        }
        safe_headers["X-TLG-Virtual-Key"] = virtual_key.name

        return JSONResponse(
            status_code=status_code,
            content=json.loads(resp_body) if resp_body else {},
            headers=safe_headers,
        )

    except Exception as exc:
        logger.error("Non-streaming forward error: %s", exc)
        latency_ms = int((time.monotonic() - start_time) * 1000)
        background_tasks.add_task(
            _log_usage, virtual_key, model, provider,
            input_tokens, 0, "error", pricing_data, latency_ms, str(exc),
        )
        return _error_response(502, f"Upstream error: {exc}", "upstream_error")
