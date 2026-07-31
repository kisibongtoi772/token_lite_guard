#!/usr/bin/env python3
"""
token_lite_guard — Quick start script
Usage: python3 run.py
"""

import sys
from pathlib import Path

# Ensure src/ is on the Python path
src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

import uvicorn
from token_lite_guard.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    print(f"\ntoken_lite_guard starting on http://localhost:{settings.port}\n")
    uvicorn.run(
        "token_lite_guard.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
        access_log=True,
    )
