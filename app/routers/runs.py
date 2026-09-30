"""Les runs (les tâches de la file), leur détail, et la galerie des vidéos publiées."""

import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, Query, Response

from app.channels import bucket_key
from app.deps import BucketStorage, MaybeStorage, Tasks
from app.storage import AVATAR_PREFIX, VOICE_PREFIX, slug
from app.task_config import AgentConfig

router = APIRouter(prefix="/api", tags=["runs"])

ERROR_TAIL = 6000
"""Une trace d'erreur est tronquée par le début : la cause est à la fin."""
LEGACY_SUFFIX = re.compile(r"_\d{4}_\d{6}$")

SUMMARY_FIELDS = {
    "_id": 0,
    "task_id": 1,
    "status": 1,
    "stage": 1,
    "stage_at": 1,
    "created_at": 1,
    "started_at": 1,
    "finished_at": 1,
    "channel_id": 1,
    "channel_label": 1,
    "channel_config.channel_name": 1,
    "channel_name": 1,  # ancien format, avant channel_config
    "result.title": 1,
    "result.video_uri": 1,
    "error": 1,
    "run_params": 1,
}


def _summary(document: dict, positions: dict[str, int]) -> dict:
    channel_name = (document.get("channel_config") or {}).get("channel_name") or document.get("channel_name", "")
    error = document.get("error")
    result = document.get("result") or {}
    return {
        "task_id": document["task_id"],
        "status": document.get("status"),
        "stage": document.get("stage"),
        "stage_at": document.get("stage_at"),
        "created_at": document.get("created_at"),
        "started_at": document.get("started_at"),
        "finished_at": document.get("finished_at"),
        "channel_id": document.get("channel_id"),
        # Une tâche poussée avant l'interface n'a pas de channel : son identifiant sans suffixe.
        "channel_label": document.get("channel_label") or LEGACY_SUFFIX.sub("", document["task_id"]),
        "channel_name": channel_name,
        "title": result.get("title"),
        "has_video": bool(result.get("video_uri")),
        "error_line": error.strip().splitlines()[-1][:300] if isinstance(error, str) and error.strip() else None,
        "run_params": document.get("run_params") or {},
        "queue_position": positions.get(document["task_id"]),
    }


def _positions(tasks: Tasks) -> dict[str, int]:
    """Le rang de chaque run en attente dans la file FIFO (1 = le prochain servi)."""
    pending = tasks.find({"status": "pending"}, {"task_id": 1}).sort("created_at", 1)
    return {document["task_id"]: rank for rank, document in enumerate(pending, start=1)}


@router.get("/queue")
def queue(tasks: Tasks) -> dict:
    return {
        "pending": tasks.count_documents({"status": "pending"}),
        "working": tasks.count_documents({"status": "working"}),
    }


@router.get("/runs")
def list_runs(
    tasks: Tasks,
    channel_id: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = None,
) -> list[dict]:
    """Les runs, du plus récent au plus ancien. Sans la config : elle pèse (source_text…)."""
    query: dict[str, Any] = {}
    if channel_id:
        query["channel_id"] = channel_id
    if status:
        query["status"] = status
    if before:
        query["created_at"] = {"$lt": before}
    positions = _positions(tasks)
    cursor = tasks.find(query, SUMMARY_FIELDS).sort("created_at", -1).limit(limit)
    return [_summary(document, positions) for document in cursor]


@router.get("/runs/{task_id}")
def get_run(task_id: str, tasks: Tasks, storage: MaybeStorage) -> dict:
    document = tasks.find_one({"task_id": task_id}, {"_id": 0})
    if document is None:
        raise HTTPException(404, f"Run {task_id} introuvable.")
    run = _summary(document, _positions(tasks))
    agent = document.get("agent_config") or {}
    result = document.get("result") or {}
    try:
        user_message = AgentConfig.model_validate(agent).user_message()
    except ValueError:
        user_message = None
    error = document.get("error")
    run.update(
        channel_version=document.get("channel_version"),
        email=(document.get("channel_config") or {}).get("email"),
        skill=agent.get("skill", ""),
        language=agent.get("language", ""),
        brief=agent.get("brief") or {},
        avatar=agent.get("avatar") or {},
        user_message=user_message,
        result=result,
        error=error[-ERROR_TAIL:] if isinstance(error, str) else None,
        video_url=None,
        download_url=None,
        avatar_url=None,
    )
    if storage is not None:
        if key := bucket_key(result.get("video_uri") or ""):
            run["video_url"] = storage.link(key)
            run["download_url"] = storage.link(key, filename=f"{slug(result.get('title') or task_id) or 'video'}.mp4")
        if key := bucket_key((agent.get("avatar") or {}).get("avatar_url") or ""):
            run["avatar_url"] = storage.link(key)
    return run


@router.delete("/runs/{task_id}", status_code=204)
def delete_run(task_id: str, tasks: Tasks) -> Response:
    """Retire un run encore en attente. Atomique : si le worker l'a pris entre-temps, 409."""
    if tasks.delete_one({"task_id": task_id, "status": "pending"}).deleted_count:
        return Response(status_code=204)
    if tasks.count_documents({"task_id": task_id}, limit=1):
        raise HTTPException(409, "Le worker a déjà pris ce run : il ne peut plus être retiré.")
    raise HTTPException(404, f"Run {task_id} introuvable.")


def _published_title(storage: BucketStorage, video_key: str, keys: set[str]) -> str | None:
    """La 1re ligne de `description.txt`, rangé à côté de la vidéo : son vrai titre, accents compris."""
    notes = video_key.removesuffix("video.mp4") + "description.txt"
    if notes not in keys:
        return None
    try:
        first = storage.read_text(notes).strip().splitlines()
    except (BotoCoreError, ClientError):  # un fichier illisible ne doit pas casser la galerie
        return None
    return first[0].strip() if first else None


@router.get("/gallery")
def gallery(tasks: Tasks, storage: BucketStorage, limit: int = Query(60, ge=1, le=200)) -> list[dict]:
    """Les vidéos publiées, lues dans le bucket : celles des runs, et celles d'avant l'interface.

    Disposition : `chaîne/date/titre[/task_id]/video.mp4`.
    """
    listing = storage.list("")
    keys = {item.key for item in listing}
    videos = [
        item
        for item in listing
        if item.key.endswith("/video.mp4") and not item.key.startswith((AVATAR_PREFIX, VOICE_PREFIX))
    ]
    videos.sort(key=lambda item: item.modified, reverse=True)
    videos = videos[:limit]
    uris = [storage.uri(item.key) for item in videos]
    runs = {
        document["result"]["video_uri"]: document
        for document in tasks.find(
            {"result.video_uri": {"$in": uris}},
            {"_id": 0, "task_id": 1, "channel_id": 1, "channel_label": 1, "result": 1, "finished_at": 1},
        )
    }
    items = []
    for item, uri in zip(videos, uris):
        parts = PurePosixPath(item.key).parts
        run = runs.get(uri, {})
        result = run.get("result") or {}
        title = result.get("title") or _published_title(storage, item.key, keys) or (
            parts[2].replace("-", " ").capitalize() if len(parts) > 2 else parts[0]
        )
        items.append(
            {
                "uri": uri,
                "title": title,
                "channel_name": parts[0],
                "date": parts[1] if len(parts) > 1 else None,
                "task_id": run.get("task_id"),
                "channel_id": run.get("channel_id"),
                "channel_label": run.get("channel_label"),
                "hashtags": result.get("hashtags") or [],
                "modified": datetime.fromtimestamp(item.modified, UTC).isoformat(),
                "video_url": storage.link(item.key),
                "download_url": storage.link(item.key, filename=f"{slug(title) or 'video'}.mp4"),
            }
        )
    return items
