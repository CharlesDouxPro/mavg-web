"""L'API du formulaire, et le front React qu'elle sert.

Un seul processus : `/api/*` pour la file de tâches, `/` pour le build du front. Une
tâche poussée arrive en `pending` dans la collection que le worker consomme.

    uv run uvicorn app.main:app --reload
"""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.catalog import load_catalog
from app.db import tasks_collection
from app.schema_docs import form_schema
from app.settings import Settings
from app.task_config import LANGUAGE_NAMES
from app.tasks import LOCKED_FIELDS, SECRET_FIELDS, TaskCreate, build_document, check

log = logging.getLogger("mavg-web")

ERROR_TAIL = 2000
"""Une trace d'erreur du worker est tronquée par le début : la cause est à la fin."""

TasksCollection = Annotated[Collection, Depends(tasks_collection)]
Limit = Annotated[int, Query(ge=1, le=100)]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="MAVG, file de tâches",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.catalog = load_catalog(settings.templates_dir)

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

    @app.get("/api/form")
    def form() -> dict:
        """Tout ce qu'il faut au front pour construire le formulaire."""
        catalog = app.state.catalog
        return {
            "schema": form_schema(),
            "templates": [
                {"id": t.id, "label": t.label, "task": t.task} for t in catalog.templates
            ],
            "languages": LANGUAGE_NAMES,
            "locked": [".".join(loc) for loc in LOCKED_FIELDS],
            "secret_fields": sorted(SECRET_FIELDS),
            "env_refs": sorted(catalog.env_refs),
        }

    @app.get("/api/tasks")
    def recent_tasks(collection: TasksCollection, limit: Limit = 20) -> list[dict]:
        """Les dernières tâches, tous statuts confondus, de la plus récente à la plus ancienne."""
        projection = {
            "_id": 0,
            "task_id": 1,
            "status": 1,
            "created_at": 1,
            "error": 1,
            "channel_config.channel_name": 1,
            "channel_name": 1,  # ancien format, avant channel_config
        }
        cursor = collection.find({}, projection).sort("created_at", -1).limit(limit)
        return [_summary(document) for document in cursor]

    def prepare(task: TaskCreate) -> dict:
        issues = check(task, app.state.catalog.env_refs)
        if issues:
            raise RequestValidationError(issues)
        return build_document(task, datetime.now(UTC))

    @app.post("/api/tasks/validate")
    def validate_task(task: TaskCreate) -> dict:
        """Le document qui serait inséré, sans l'insérer : l'équivalent de `--dry-run`."""
        document = prepare(task)
        return {"task_id": document["task_id"], "document": jsonable_encoder(document)}

    @app.post("/api/tasks", status_code=201)
    def create_task(task: TaskCreate, collection: TasksCollection) -> dict:
        document = prepare(task)
        task_id = document["task_id"]
        # Le worker met à jour le statut par task_id : deux documents homonymes
        # partageraient leur statut.
        if collection.count_documents({"task_id": task_id}, limit=1):
            raise HTTPException(409, f"{task_id} existe déjà : renvoyez dans une seconde.")
        collection.insert_one(document)
        log.info("Tâche poussée : %s", task_id)
        return {"task_id": task_id, "pending": collection.count_documents({"status": "pending"})}

    if settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="front")
    return app


def _summary(document: dict) -> dict:
    channel = (document.get("channel_config") or {}).get("channel_name")
    error = document.get("error")
    return {
        "task_id": document.get("task_id"),
        "status": document.get("status"),
        "created_at": document.get("created_at"),
        "channel_name": channel or document.get("channel_name", ""),
        "error": error[-ERROR_TAIL:] if isinstance(error, str) else None,
    }


app = create_app()
