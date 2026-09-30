"""Avatars et voix du bucket ; l'accès protégé par HTTP Basic."""

import base64
import json
from pathlib import Path

import pytest
from conftest import upload
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def test_avatars_list_folder_and_root_media_only(client, storage):
    storage.put("Capture.png", kind="image/png")
    storage.put("voices/fr/male/20-30/hugo.wav")
    storage.put("hudex-foot/2026-09-30/x/video.mp4")
    names = {a["name"]: a["kind"] for a in client.get("/api/assets/avatars").json()}
    assert names == {"nova": "video", "Capture": "image"}


def test_upload_never_overwrites(client, storage):
    first = upload(client, "Mateo Tech")
    assert first.status_code == 201, first.text
    assert first.json()["uri"] == "s3://mavg-object-storage/avatars/mateo-tech.png"
    assert upload(client, "Mateo Tech").json()["uri"].endswith("avatars/mateo-tech-2.png")


def test_upload_refuses_other_formats(client):
    assert upload(client, "x", filename="script.sh").status_code == 422


def test_voices_are_parsed_from_their_key(client, storage):
    storage.put("voices/fr/male/20-30/hugo.wav")
    storage.put("voices/fr/male/20-30/hugo.json", json.dumps({"name": "hugo", "description": "Parisien", "text": "Bonjour", "duration_s": 11.9}).encode())
    [voice] = client.get("/api/assets/voices").json()
    assert voice == {
        "uri": "s3://mavg-object-storage/voices/fr/male/20-30/hugo.wav", "name": "hugo",
        "language": "fr", "sex": "male", "age_range": "20-30",
        "url": "https://signed.example/voices/fr/male/20-30/hugo.wav?inline",
    }
    info = client.get("/api/assets/voices/info", params={"uri": voice["uri"]}).json()
    assert info["description"] == "Parisien"
    assert client.get("/api/assets/voices/info", params={"uri": "s3://mavg-object-storage/avatars/nova.mp4"}).status_code == 422


def test_service_refuses_to_start_unprotected():
    with pytest.raises(RuntimeError, match="WEB_USER"):
        create_app(Settings())


def test_basic_auth(monkeypatch):
    app = create_app(Settings(auth_user="charles", auth_password="s3cret", static_dir=Path("/nonexistent")))
    client = TestClient(app)
    good = "Basic " + base64.b64encode(b"charles:s3cret").decode()
    bad = "Basic " + base64.b64encode(b"charles:nope").decode()
    assert client.get("/api/health").status_code == 200
    unauthorized = client.get("/api/catalog")
    assert unauthorized.status_code == 401 and "Basic" in unauthorized.headers["www-authenticate"]
    assert client.get("/api/catalog", headers={"Authorization": bad}).status_code == 401
    assert client.get("/api/catalog", headers={"Authorization": good}).status_code == 200
