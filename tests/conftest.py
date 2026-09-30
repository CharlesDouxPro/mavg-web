"""Fixtures : une base Mongo en mémoire (mongomock) et un bucket en mémoire.

Rien ne part vers la vraie base ni vers le vrai stockage.
"""

import copy
import io
import time

import mongomock
import pytest
from fastapi.testclient import TestClient

from app.db import channels_collection, tasks_collection
from app.main import create_app
from app.settings import Settings
from app.storage import Listed

BUCKET = "mavg-object-storage"


class FakeStorage:
    """Le sous-ensemble de `app.storage.Storage` dont les routes se servent."""

    def __init__(self):
        self.bucket = BUCKET
        self.objects: dict[str, tuple[bytes, str, float]] = {}

    def put(self, key: str, data: bytes = b"x", kind: str = "application/octet-stream") -> None:
        self.objects[key] = (data, kind, time.time() + len(self.objects))

    def uri(self, key):
        return f"s3://{BUCKET}/{key}"

    def link(self, key, *, filename=None, expires_s=3600):
        mode = f"attachment:{filename}" if filename else "inline"
        return f"https://signed.example/{key}?{mode}"

    def list(self, prefix, shallow=False):
        return [
            Listed(key, len(data), modified)
            for key, (data, _, modified) in self.objects.items()
            if key.startswith(prefix) and not (shallow and "/" in key[len(prefix):])
        ]

    def exists(self, key):
        return key in self.objects

    def read_text(self, key):
        return self.objects[key][0].decode()

    def read_json(self, key):
        import json

        return json.loads(self.objects[key][0])

    def upload(self, stream, key, kind):
        self.put(key, stream.read(), kind)

    def free_key(self, prefix, stem, suffix):
        candidate, index = f"{prefix}{stem}{suffix}", 2
        while candidate in self.objects:
            candidate, index = f"{prefix}{stem}-{index}{suffix}", index + 1
        return candidate


@pytest.fixture
def db():
    return mongomock.MongoClient(tz_aware=True).mgdb


@pytest.fixture
def storage():
    fake = FakeStorage()
    fake.put("avatars/nova.mp4", kind="video/mp4")
    return fake


@pytest.fixture
def client(db, storage):
    app = create_app(Settings(auth_disabled=True, static_dir=__import__("pathlib").Path("/nonexistent")))
    app.dependency_overrides[tasks_collection] = lambda: db.tasks
    app.dependency_overrides[channels_collection] = lambda: db.channels
    app.state.storage = storage
    return TestClient(app)


CHANNEL = {
    "id": "foot-scoop-fr",
    "name": "Actu foot · scoop FR",
    "description": "Un article foot raconté comme un scoop.",
    "channel_config": {"channel_name": "hudex-foot", "email": "ops@example.com"},
    "parameters": [
        {"name": "source_url", "type": "url", "required": True, "description": "L'article"},
        {"name": "angle", "type": "string", "default": "le transfert"},
        {"name": "duree", "type": "number", "default": "45"},
    ],
    "agent_config": {
        "skill": "tiktok-news-article-presentation",
        "language": "fr",
        "brief": {
            "prompt": "Résume ${source_url} sous l'angle ${angle}, en ${duree} secondes.",
            "mood": "urgence",
        },
        "avatar": {
            "name": "Nova",
            "avatar_url": f"s3://{BUCKET}/avatars/nova.mp4",
            "description": "présentatrice",
            "appearance": "woman, navy blazer",
        },
        "publication": {"must_include": ["${source_url}"]},
    },
}


@pytest.fixture
def channel():
    return copy.deepcopy(CHANNEL)


@pytest.fixture
def created(client, channel):
    response = client.post("/api/channels", json=channel)
    assert response.status_code == 201, response.text
    return response.json()["channel"]


def errors(response) -> dict[str, str]:
    """{chemin du champ: message} d'une réponse 422."""
    assert response.status_code == 422, response.text
    return {".".join(map(str, e["loc"][1:])): e["msg"] for e in response.json()["detail"]}


def upload(client, name: str, data: bytes = b"\x89PNG", filename: str = "photo.png"):
    return client.post(
        "/api/assets/avatars",
        files={"file": (filename, io.BytesIO(data), "image/png")},
        data={"name": name},
    )
