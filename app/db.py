"""La file de tâches : la collection Mongo que le worker consomme."""

from functools import lru_cache

from fastapi import HTTPException, Request
from pymongo import MongoClient
from pymongo.collection import Collection


@lru_cache(maxsize=1)
def _client(connection_string: str) -> MongoClient:
    # Un seul client par processus : il porte son pool de connexions. Le timeout court
    # fait échouer une requête en quelques secondes plutôt que de la laisser pendre.
    return MongoClient(connection_string, serverSelectionTimeoutMS=5000, tz_aware=True)


def tasks_collection(request: Request) -> Collection:
    settings = request.app.state.settings
    if not settings.mongo_connection_string or not settings.mongo_database:
        raise HTTPException(
            503,
            "MongoDB n'est pas configuré : renseigner MONGO_CONNECTION_STRING et "
            "MONGO_PLATFORM_DATABASE_NAME.",
        )
    client = _client(settings.mongo_connection_string)
    return client[settings.mongo_database][settings.mongo_collection]
