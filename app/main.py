"""MAVG Studio : l'API des channels et des runs, et le front React qu'elle sert.

Un seul processus : `/api/*` pour les channels, les runs, les assets et l'assistant, `/` pour le
build du front. Un run lancé arrive en `pending` dans la collection que le worker consomme.

    uv run uvicorn app.main:create_app --factory --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from app import auth
from app.db import _client, ensure_indexes
from app.routers import assets, assistant, catalog, channels, runs
from app.settings import Settings
from app.storage import Storage

log = logging.getLogger("mavg-web")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    auth.check_settings(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.mongo_configured:
            try:
                database = _client(settings.mongo_connection_string)[settings.mongo_database]
                ensure_indexes(database[settings.mongo_collection])
            except PyMongoError as exc:
                log.warning("Index non vérifiés au démarrage : %s", exc)
        yield

    app = FastAPI(
        title="MAVG Studio",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.storage = (
        Storage(settings.s3_access_key, settings.s3_secret_key)
        if settings.s3_access_key and settings.s3_secret_key
        else None
    )
    app.middleware("http")(auth.middleware(settings))

    @app.exception_handler(PyMongoError)
    async def mongo_unavailable(request: Request, exc: PyMongoError) -> JSONResponse:
        log.exception("MongoDB : %s", exc)
        return JSONResponse(
            {"detail": "MongoDB injoignable. Le détail est dans les logs du service."},
            status_code=503,
        )

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    for router in (catalog.router, channels.router, runs.router, assets.router, assistant.router):
        app.include_router(router)

    if settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="front")
    return app
