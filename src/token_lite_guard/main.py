"""
token_lite_guard — FastAPI Application
Main entry point: mounts proxy + management API + static dashboard.
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
from .proxy.forwarder import close_http_client

# ─── Logging setup ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("token_lite_guard")

# ─── Static files path ────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"


# ─── Lifespan (startup / shutdown) ───────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    settings = get_settings()

    logger.info("=" * 55)
    logger.info("  🛡️  token_lite_guard  v0.1.0  starting up...")
    logger.info("=" * 55)

    await init_db()

    if settings.openai_api_key:
        logger.info("✓ OpenAI provider configured")
    else:
        logger.warning("⚠ OPENAI_API_KEY not set — OpenAI proxy will fail")

    if settings.anthropic_api_key:
        logger.info("✓ Anthropic provider configured")
    else:
        logger.info("  Anthropic provider not configured (optional)")

    logger.info(f"✓ Dashboard → http://localhost:{settings.port}")
    logger.info(f"✓ Proxy endpoint → http://localhost:{settings.port}/v1")
    logger.info("=" * 55)

    yield  # Application runs here

    # Shutdown
    logger.info("Shutting down token_lite_guard...")
    await close_http_client()
    await close_db()
    logger.info("Goodbye! 👋")


# ─── App factory ─────────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title="token_lite_guard",
        description="A lightweight AI Gateway that protects your LLM budget",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # CORS — allow all origins since this is localhost-only
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ─── Routers ────────────────────────────────────────────────
    app.include_router(proxy_router)   # /v1/* proxy
    app.include_router(keys_router)    # /api/keys
    app.include_router(stats_router)   # /api/stats

    # ─── Static files (CSS, JS) ──────────────────────────────────
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ─── Dashboard SPA ───────────────────────────────────────────
    @app.get("/", include_in_schema=False)
    async def dashboard():
        """Serve the dashboard HTML."""
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return HTMLResponse("<h1>token_lite_guard</h1><p>Dashboard not found.</p>")

    # ─── Health check ────────────────────────────────────────────
    @app.get("/health", tags=["system"])
    async def health():
        """Quick health check endpoint."""
        return {"status": "ok", "service": "token_lite_guard", "version": "0.1.0"}

    return app


# ─── App instance ─────────────────────────────────────────────────
app = create_app()


# ─── Entrypoint for `token-lite-guard` CLI ───────────────────────
def run():
    """CLI entrypoint: `token-lite-guard` or `python -m token_lite_guard`."""
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "token_lite_guard.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
    )
