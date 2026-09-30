"""L'API contre une file Mongo en mémoire (mongomock) : rien ne part vers la vraie base."""

import copy
import filecmp
from datetime import UTC, datetime
from pathlib import Path

import mongomock
import pytest
from fastapi.testclient import TestClient

from app.db import tasks_collection
from app.main import create_app
from app.settings import ROOT, Settings
from app.task_config import load_task

WORKER_REPO = ROOT.parent / "mavg"


@pytest.fixture
def collection():
    return mongomock.MongoClient(tz_aware=True).db.tasks


@pytest.fixture
def client(collection):
    settings = Settings(
        mongo_connection_string="",
        mongo_database="",
        mongo_collection="tasks",
        templates_dir=ROOT / "templates",
        static_dir=Path("/nonexistent"),
    )
    app = create_app(settings)
    app.dependency_overrides[tasks_collection] = lambda: collection
    return TestClient(app)


@pytest.fixture
def task(client):
    """Le premier modèle, rendu envoyable : il ne manque que l'email du rapport."""
    template = client.get("/api/form").json()["templates"][0]["task"]
    task = copy.deepcopy(template)
    task["channel_config"]["email"] = "ops@example.com"
    return task


class Frozen:
    def __init__(self, instant: datetime):
        self.instant = instant

    def now(self, tz=None) -> datetime:
        return self.instant


def errors(response) -> dict[str, str]:
    assert response.status_code == 422, response.text
    return {".".join(map(str, e["loc"][1:])): e["msg"] for e in response.json()["detail"]}


def test_form_exposes_schema_templates_and_rules(client):
    form = client.get("/api/form").json()
    assert {t["id"] for t in form["templates"]} >= {"news_football", "diy_etagere"}
    assert "FOUNDRY_API_KEY" in form["env_refs"]
    assert "agent_config.subtitles.ffmpeg_bin" in form["locked"]
    render = form["schema"]["$defs"]["RenderSettings"]["properties"]
    assert "Clips en vol" in render["concurrency"]["description"]


def test_push_inserts_a_pending_task_the_worker_can_load(client, collection, task, monkeypatch):
    response = client.post("/api/tasks", json=task)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["task_id"].startswith(f"{task['task_id']}_")
    assert body["pending"] == 1

    document = collection.find_one({"task_id": body["task_id"]})
    assert document["status"] == "pending"
    assert document["created_at"].tzinfo is not None
    # Le secret reste une référence en base ; le worker la résout à la lecture.
    assert document["agent_config"]["models"]["master_mind"]["token"] == "${FOUNDRY_API_KEY}"
    monkeypatch.setenv("FOUNDRY_API_KEY", "resolved")
    loaded = load_task(document)
    assert loaded.agent_config.models.master_mind.token == "resolved"
    assert loaded.channel_config.email == "ops@example.com"


def test_validate_does_not_insert(client, collection, task):
    response = client.post("/api/tasks/validate", json=task)
    assert response.status_code == 200, response.text
    assert response.json()["document"]["status"] == "pending"
    assert collection.count_documents({}) == 0


def test_advanced_options_reach_the_document(client, collection, task):
    task["agent_config"]["models"]["master_mind"]["model_name"] = "claude-sonnet-5"
    task["agent_config"]["render"]["seed"] = 7
    task_id = client.post("/api/tasks", json=task).json()["task_id"]
    document = collection.find_one({"task_id": task_id})
    assert document["agent_config"]["models"]["master_mind"]["model_name"] == "claude-sonnet-5"
    assert document["agent_config"]["render"]["seed"] == 7


@pytest.mark.parametrize("task_id", ["../evil", "a/b", "_hidden", "", "x" * 65])
def test_task_id_must_be_a_folder_name(client, task, task_id):
    task["task_id"] = task_id
    assert "task_id" in errors(client.post("/api/tasks/validate", json=task))


def test_clear_text_secret_is_refused(client, collection, task):
    task["agent_config"]["models"]["slm"]["token"] = "sk-live-123"
    found = errors(client.post("/api/tasks", json=task))
    assert "agent_config.models.slm.token" in found
    assert collection.count_documents({}) == 0


def test_unknown_env_reference_is_refused(client, task):
    # Le worker résout toute ${VAR} : une référence libre ferait fuiter ses secrets.
    task["agent_config"]["brief"]["prompt"] = "Résume ${MONGO_CONNECTION_STRING}"
    assert (
        "MONGO_CONNECTION_STRING"
        in errors(client.post("/api/tasks/validate", json=task))["agent_config.brief.prompt"]
    )


def test_worker_machine_settings_are_locked(client, task):
    task["agent_config"]["subtitles"]["ffmpeg_bin"] = "/bin/sh"
    task["agent_config"]["render"]["output_dir"] = "/etc"
    found = errors(client.post("/api/tasks/validate", json=task))
    assert {"agent_config.subtitles.ffmpeg_bin", "agent_config.render.output_dir"} <= set(found)


def test_email_is_required(client, task):
    task["channel_config"]["email"] = ""
    assert "channel_config.email" in errors(client.post("/api/tasks/validate", json=task))


def test_same_task_in_the_same_second_is_refused(client, collection, task, monkeypatch):
    # Le worker met à jour le statut par task_id : deux homonymes partageraient le leur.
    frozen = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("app.main.datetime", Frozen(frozen))
    assert client.post("/api/tasks", json=task).status_code == 201
    assert client.post("/api/tasks", json=task).status_code == 409
    assert collection.count_documents({}) == 1


def test_recent_tasks_newest_first(client, task, monkeypatch):
    task_ids = []
    for minute, base in enumerate(("first", "second")):
        monkeypatch.setattr(
            "app.main.datetime", Frozen(datetime(2026, 9, 25, 12, minute, tzinfo=UTC))
        )
        task["task_id"] = base
        task_ids.append(client.post("/api/tasks", json=task).json()["task_id"])
    listed = client.get("/api/tasks").json()
    assert [t["task_id"] for t in listed] == task_ids[::-1]
    assert listed[0]["status"] == "pending"
    assert listed[0]["channel_name"] == task["channel_config"]["channel_name"]


def test_mongo_not_configured_is_a_clear_503():
    settings = Settings("", "", "tasks", ROOT / "templates", Path("/nonexistent"))
    response = TestClient(create_app(settings)).get("/api/tasks")
    assert response.status_code == 503
    assert "MONGO_CONNECTION_STRING" in response.json()["detail"]


@pytest.mark.skipif(not (WORKER_REPO / "task_config.py").exists(), reason="repo mavg absent")
def test_schema_copy_matches_the_worker():
    assert filecmp.cmp(ROOT / "app" / "task_config.py", WORKER_REPO / "task_config.py"), (
        "app/task_config.py a divergé du worker : lancer scripts/sync_schema.sh"
    )
