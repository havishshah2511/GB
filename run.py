#!/usr/bin/env python
"""Dev entry point:  python run.py"""
from __future__ import annotations

import os

import uvicorn

from app.config import settings

if __name__ == "__main__":
    # RELOAD=1 restarts on source edits. Off by default: the reloader spawns a
    # second process, which would run two background workers.
    reload = os.getenv("RELOAD", "0").strip().lower() in ("1", "true", "yes")
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=reload,
        reload_dirs=["app"] if reload else None,
        log_level="info",
    )
