"""HTTP forwarding engine with streaming support for multiple providers."""

import json
import logging
import re
import time
from typing import AsyncGenerator, Optional

import httpx

from ..config import MODEL_PROVIDER_MAP, get_settings

logger = logging.getLogger(__name__)

# Reusable async HTTP client (initialized once at startup)
_http_client: Optional[httpx.AsyncClient] = None

# Hop-by-hop headers that must not be forwarded
_HOP_BY_HOP = frozenset({
    "host", "content-length", "transfer-encoding",
    "connection", "keep-alive", "upgrade", "proxy-authorization",
    "proxy-authenticate", "trailer", "te",
})


def _make_client(timeout_seconds: int = 120) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=10.0,
            read=float(timeout_seconds),
            write=30.0,
            pool=5.0,
        ),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=30),
    )


def get_http_client() -> httpx.AsyncClient:
    """Return the shared HTTP client, creating it on first access."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        settings = get_settings()
        _http_client = _make_client(settings.upstream_timeout_seconds)
    return _http_client


async def close_http_client() -> None:
    """Dispose the shared HTTP client on application shutdown."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


def detect_provider(model: str) -> str:
    """
    Infer the provider identifier from the model name.

    Uses the MODEL_PROVIDER_MAP prefix list defined in config.py.
    Falls back to 'openai' when no prefix matches.
    """
    model_lower = model.lower()
    for prefix, provider in MODEL_PROVIDER_MAP:
        if model_lower.startswith(prefix.lower()):
            return provider
    return "openai"


def _build_forward_headers(
    original_headers: dict,
    real_api_key: str,
    auth_style: str,
    extra_headers: Optional[dict] = None,
) -> dict:
    """
    Construct the header set for the upstream request.

    Strips hop-by-hop and sensitive headers, then injects the real
    API key using the authentication style required by the provider.

    auth_style values:
      bearer    — Authorization: Bearer <key>         (OpenAI, Groq, Mistral, etc.)
      x-api-key — x-api-key: <key>                   (Anthropic)
      api-key   — api-key: <key>                      (Azure OpenAI)
      none      — No authentication header injected   (fully open local servers)
    """
    forward: dict[str, str] = {}

    for key, value in original_headers.items():
        if key.lower() in _HOP_BY_HOP:
            continue
        forward[key] = value

    # Remove any virtual key the caller may have set
    forward.pop("authorization", None)
    forward.pop("x-api-key", None)
    forward.pop("api-key", None)

    # Inject the real authentication credential
    match auth_style:
        case "bearer":
            forward["authorization"] = f"Bearer {real_api_key}"
        case "x-api-key":
            forward["x-api-key"] = real_api_key
            forward.setdefault("anthropic-version", "2023-06-01")
        case "api-key":
            forward["api-key"] = real_api_key
        case "none":
            pass  # Local providers with no auth requirement

    if extra_headers:
        forward.update(extra_headers)

    return forward


async def forward_streaming(
    url: str,
    method: str,
    headers: dict,
    body: bytes,
    real_api_key: str,
    auth_style: str = "bearer",
    extra_headers: Optional[dict] = None,
) -> AsyncGenerator[tuple[bytes, int], None]:
    """
    Forward a request upstream and yield response chunks as they arrive.

    Yields:
        (chunk_bytes, output_tokens_counted_from_chunk)

    Token deduction is handled by the caller after the stream completes.
    """
    from .token_counter import parse_sse_chunk_tokens

    forward_headers = _build_forward_headers(dict(headers), real_api_key, auth_style, extra_headers)
    client = get_http_client()

    model = "gpt-4o"
    try:
        body_json = json.loads(body)
        model = body_json.get("model", "gpt-4o")
    except Exception:
        pass

    async with client.stream(method, url, headers=forward_headers, content=body) as response:
        async for chunk in response.aiter_bytes():
            if not chunk:
                continue

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
    auth_style: str = "bearer",
    extra_headers: Optional[dict] = None,
) -> tuple[int, dict, bytes]:
    """
    Forward a non-streaming request and return the complete response.

    Returns:
        (status_code, response_headers, response_body_bytes)
    """
    forward_headers = _build_forward_headers(dict(headers), real_api_key, auth_style, extra_headers)
    client = get_http_client()

    response = await client.request(
        method=method,
        url=url,
        headers=forward_headers,
        content=body,
    )

    return response.status_code, dict(response.headers), response.content


def build_upstream_url(provider: str, path: str, custom_base_url: Optional[str] = None) -> str:
    """
    Construct the full upstream URL for a given provider and request path.

    For custom providers, pass the base_url directly via `custom_base_url`.
    The /v1 prefix in `path` is stripped before appending to the base URL
    because the base URL already includes it.

    Examples:
      provider="openai", path="/v1/chat/completions"
      -> "https://api.openai.com/v1/chat/completions"

      custom_base_url="http://localhost:8080/v1", path="/v1/chat/completions"
      -> "http://localhost:8080/v1/chat/completions"
    """
    settings = get_settings()

    if custom_base_url:
        base = custom_base_url.rstrip("/")
    else:
        base = settings.get_provider_base_url(provider).rstrip("/")

    clean_path = re.sub(r"^/v1", "", path)
    return f"{base}{clean_path}"
