"""CivicPulse backend entry point.

Run locally:  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .ai import build_ai
from .config import Settings, get_settings
from .routers.api import router as api_router
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("civicpulse")


def create_app(settings: Settings | None = None, store: Store | None = None, ai=None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.store = store or Store(settings.db_path)
        app.state.ai = ai or build_ai(settings.gemini_api_key, settings.gemini_model, settings.gemini_timeout_s)
        log.info("CivicPulse up. ai_mode=%s db=%s uploads=%s", app.state.ai.mode, settings.db_path, settings.uploads_path)
        yield
        if store is None:
            app.state.store.close()

    app = FastAPI(
        title="CivicPulse API",
        version="0.1.0",
        description="From complaint to closure, with proof. Civic accountability layer for Bengaluru.",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in settings.cors_origins.split(",")] if settings.cors_origins else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")

    settings.uploads_path.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(settings.uploads_path)), name="uploads")

    dist = Path(settings.frontend_dist)
    if (dist / "index.html").exists():
        assets = dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str, request: Request):
            candidate = dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        async def root():
            return JSONResponse(
                {
                    "name": "CivicPulse API",
                    "docs": "/docs",
                    "hint": "Build the frontend (cd frontend && npm run build) to serve the PWA from this port.",
                }
            )

    return app


app = create_app()
