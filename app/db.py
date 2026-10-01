"""Les collections : la file de tâches que le worker consomme, les channels, et les
conversations de l'assistant."""

import logging
from functools import lru_cache

from fastapi import HTTPException, Request
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.settings import Settings

log = logging.getLogger("mavg-web")


@lru_cache(maxsize=1)
def _client(connection_string: str) -> MongoClient:
    # Un seul client par processus : il porte son pool de connexions. Le timeout court
    # fait échouer une requête en quelques secondes plutôt que de la laisser pendre.
    return MongoClient(connection_string, serverSelectionTimeoutMS=5000, tz_aware=True)


def _collection(settings: Settings, name: str) -> Collection:
    if not settings.mongo_configured:
        raise HTTPException(
            503,
            "MongoDB n'est pas configuré : renseigner MONGO_CONNECTION_STRING et "
            "MONGO_PLATFORM_DATABASE_NAME.",
        )
    return _client(settings.mongo_connection_string)[settings.mongo_database][name]


def tasks_collection(request: Request) -> Collection:
    settings = request.app.state.settings
    return _collection(settings, settings.mongo_collection)


def channels_collection(request: Request) -> Collection:
    settings = request.app.state.settings
    return _collection(settings, settings.channels_collection)


def assistant_collection(request: Request) -> Collection:
    settings = request.app.state.settings
    return _collection(settings, settings.assistant_collection)


def ensure_indexes(tasks: Collection) -> None:
    """Les index de la file, créés s'ils manquent. Jamais bloquant : un échec se logge.

    `task_id` unique : le worker met à jour le statut par `task_id`, deux homonymes
    partageraient le leur. `status + created_at` sert la file FIFO.
    """
    specs = [
        ([("task_id", ASCENDING)], {"unique": True}),
        ([("status", ASCENDING), ("created_at", ASCENDING)], {}),
        ([("channel_id", ASCENDING), ("created_at", DESCENDING)], {}),
        ([("created_at", DESCENDING)], {}),
    ]
    for keys, options in specs:
        try:
            tasks.create_index(keys, **options)
        except PyMongoError as exc:
            log.warning("Index %s non créé : %s", keys, exc)
