"""
token_lite_guard — FastAPI Application
Entry point: mounts proxy, management API, and static dashboard.
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import close_db, init_db
from .proxy.router import router as proxy_router
from .api.keys import router as keys_router
from .api.stats import router as stats_router
from .api.providers import router as providers_router
from .api.settings import router as settings_router
from .proxy.forwarder import close_http_client

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("token_lite_guard")

STATIC_DIR = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup initialization and shutdown cleanup."""
    settings = get_settings()

    logger.info("=" * 60)
    logger.info("  token_lite_guard  v0.1.0  starting")
    logger.info("=" * 60)

    await init_db()

    # Report provider configuration status
    configured = []
    unconfigured = []
    local_providers = {"ollama", "lmstudio"}
    from .config import BUILTIN_PROVIDERS
    for pid in BUILTIN_PROVIDERS:
        if pid in local_providers or settings.is_provider_configured(pid):
            configured.append(pid)
        else:
            unconfigured.append(pid)

    if configured:
        logger.info("Configured providers: %s", ", ".join(configured))
    if unconfigured:
        logger.info("Unconfigured providers: %s", ", ".join(unconfigured))

    logger.info("Dashboard : http://localhost:%d", settings.port)
    logger.info("Proxy     : http://localhost:%d/v1", settings.port)
    logger.info("API docs  : http://localhost:%d/api/docs", settings.port)
    logger.info("=" * 60)

    yield

    logger.info("Shutting down token_lite_guard")
    await close_http_client()
    await close_db()
    logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="token_lite_guard",
        description=(
            "A lightweight local AI Gateway that enforces token budgets "
            "for AI agents and tools by proxying requests to LLM providers."
        ),
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers — order matters: proxy must come before static mount
    app.include_router(proxy_router)      # /v1/*
    app.include_router(keys_router)       # /api/keys
    app.include_router(stats_router)      # /api/stats
    app.include_router(providers_router)  # /api/providers
    app.include_router(settings_router)   # /api/settings

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def dashboard():
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return HTMLResponse("<h1>token_lite_guard</h1><p>Dashboard not found.</p>")

    @app.get("/health", tags=["system"], summary="Health check")
    async def health():
        """Returns service status and version."""
        return {"status": "ok", "service": "token_lite_guard", "version": "0.1.0"}

    return app


# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = create_app()


def run():
    """CLI entrypoint: invoked by the `token-lite-guard` console script."""
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "token_lite_guard.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
    )
