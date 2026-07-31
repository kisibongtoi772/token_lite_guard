"""HTTP forwarding engine with streaming support."""

import json
import logging
import re
import time
from typing import AsyncGenerator

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

# Timeout settings for upstream LLM calls
UPSTREAM_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=120.0,   # LLMs can be slow
    write=30.0,
    pool=5.0,
)

# Reusable async HTTP client (created once)
_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return the shared HTTP client, creating it on first call."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=UPSTREAM_TIMEOUT,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _http_client


async def close_http_client() -> None:
    """Close the shared HTTP client on shutdown."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


def detect_provider(model: str) -> str:
    """
    Auto-detect the LLM provider from the model name.

    gpt-*, o1*, o3* → openai
    claude-* → anthropic
    """
    model_lower = model.lower()
    if model_lower.startswith(("gpt-", "o1", "o3", "text-davinci", "whisper")):
        return "openai"
    if model_lower.startswith("claude"):
        return "anthropic"
    # Default fallback
    return "openai"


def _build_forward_headers(
    original_headers: dict,
    real_api_key: str,
    provider: str,
) -> dict:
    """
    Build headers for the upstream request.
    Strips the virtual key and injects the real one.
    """
    # Start clean — only forward safe headers
    forward = {}

    for key, value in original_headers.items():
        key_lower = key.lower()
        # Pass through content-type, accept, user-agent, etc.
        # Skip hop-by-hop headers and host
        if key_lower in ("host", "content-length", "transfer-encoding",
                         "connection", "keep-alive", "upgrade", "proxy-authorization"):
            continue
        forward[key] = value

    # Inject the real API key
    if provider == "anthropic":
        forward["x-api-key"] = real_api_key
        forward["anthropic-version"] = forward.get("anthropic-version", "2023-06-01")
        # Remove OpenAI-style auth if present
        forward.pop("authorization", None)
    else:
        forward["authorization"] = f"Bearer {real_api_key}"

    return forward


async def forward_streaming(
    url: str,
    method: str,
    headers: dict,
    body: bytes,
    real_api_key: str,
    provider: str,
) -> AsyncGenerator[tuple[bytes, int], None]:
    """
    Forward a request upstream and stream the response back.

    Yields:
        (chunk_bytes, output_tokens_in_chunk)

    The caller is responsible for deducting tokens after the stream completes.
    """
    from .token_counter import parse_sse_chunk_tokens

    forward_headers = _build_forward_headers(dict(headers), real_api_key, provider)
    client = get_http_client()

    # Try to extract model from body for token counting
    model = "gpt-4o"  # default
    try:
        body_json = json.loads(body)
        model = body_json.get("model", "gpt-4o")
    except (json.JSONDecodeError, Exception):
        pass

    async with client.stream(method, url, headers=forward_headers, content=body) as response:
        # Forward the status code to the caller (handled at router level)
        async for chunk in response.aiter_bytes():
            if not chunk:
                continue

            # Try to count tokens from this SSE chunk
            output_tokens = 0
            try:
                decoded = chunk.decode("utf-8", errors="ignore")
                for line in decoded.split("\n"):
                    line = line.strip()
                    if line.startswith("data: "):
                        output_tokens += parse_sse_chunk_tokens(line[6:], model)
            except Exception:
                pass

            yield chunk, output_tokens


async def forward_non_streaming(
    url: str,
    method: str,
    headers: dict,
    body: bytes,
    real_api_key: str,
    provider: str,
) -> tuple[int, dict, bytes]:
    """
    Forward a non-streaming request and return the full response.

    Returns:
        (status_code, response_headers, response_body)
    """
    forward_headers = _build_forward_headers(dict(headers), real_api_key, provider)
    client = get_http_client()

    response = await client.request(
        method=method,
        url=url,
        headers=forward_headers,
        content=body,
    )

    return response.status_code, dict(response.headers), response.content


def build_upstream_url(provider: str, path: str) -> str:
    """
    Construct the full upstream URL.

    e.g. path="/v1/chat/completions" → "https://api.openai.com/v1/chat/completions"
    """
    settings = get_settings()
    base_url = settings.get_provider_base_url(provider).rstrip("/")

    # Strip the leading /v1 from the path since base_url already includes it
    clean_path = re.sub(r"^/v1", "", path)
    return f"{base_url}{clean_path}"
