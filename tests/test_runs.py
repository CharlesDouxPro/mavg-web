"""Lancer un run, le suivre, le retirer ; la galerie des vidéos publiées."""

import filecmp
import re
from datetime import UTC, datetime

import pytest
from conftest import errors

from app.issues import strings
from app.settings import ROOT
from app.task_config import load_task

WORKER_REPO = ROOT.parent / "mavg"
VALUES = {"source_url": "https://lequipe.fr/gyokeres", "angle": "la revanche"}
SECRET_PATHS = re.compile(r"agent_config\.(models\.\w+\.(base_url|token)|scraper\.token|storage\.(access|secret)_key)$")


def launch(client, values=VALUES, **extra):
    return client.post("/api/channels/foot-scoop-fr/runs", json={"values": values, **extra})


def test_launch_inserts_a_rendered_snapshot(client, db, created):
    response = launch(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["queue_position"] == 1 and body["task_id"].startswith("foot-scoop-fr_")

    doc = db.tasks.find_one({"task_id": body["task_id"]})
    agent = doc["agent_config"]
    assert doc["status"] == "pending"
    assert agent["brief"]["prompt"] == "Résume https://lequipe.fr/gyokeres sous l'angle la revanche, en 45 secondes."
    assert agent["publication"]["must_include"] == ["https://lequipe.fr/gyokeres"]
    # Les valeurs restent aussi dans params : « SUJET PRÉCIS » et source_text marchent toujours.
    assert agent["params"] == {"source_url": "https://lequipe.fr/gyokeres", "angle": "la revanche", "duree": "45"}
    assert doc["channel_id"] == "foot-scoop-fr" and doc["channel_version"] == 1
    assert doc["run_params"]["angle"] == "la revanche" and doc["schema_version"] == 3
    # Adresses et clés viennent du registre, pas du channel.
    assert agent["models"]["master_mind"]["token"] == "${FOUNDRY_API_KEY}"
    assert agent["models"]["image_generator"]["model_name"] == "MiniMaxAI/MiniMax-H3"


def test_launched_task_loads_in_the_worker_and_leaks_nothing(client, db, created, monkeypatch):
    task_id = launch(client).json()["task_id"]
    doc = db.tasks.find_one({"task_id": task_id}, {"_id": 0})
    for loc, text in strings(doc):
        if "${" in text:
            assert SECRET_PATHS.search(".".join(map(str, loc))), f"${{…}} hors secret : {loc}"
    monkeypatch.setenv("FOUNDRY_API_KEY", "resolved")
    monkeypatch.setenv("FOUNDRY_RESOURCE", "hudex")
    task = load_task(doc)
    assert task.agent_config.models.master_mind.token == "resolved"
    assert "SUJET PRÉCIS" in task.agent_config.user_message()


def test_required_unknown_and_invalid_values(client, created):
    found = errors(launch(client, {"angle": "x", "duree": "beaucoup", "intrus": "1"}))
    assert set(found) == {"values.source_url", "values.duree", "values.intrus"}
    assert "requis" in found["values.source_url"]


def test_a_value_cannot_inject_a_worker_variable(client, created):
    found = errors(launch(client, {**VALUES, "angle": "${FOUNDRY_API_KEY}"}))
    assert "values.angle" in found


def test_optional_empty_value_is_omitted(client, db, created):
    task_id = launch(client, {"source_url": VALUES["source_url"], "angle": ""}).json()["task_id"]
    agent = db.tasks.find_one({"task_id": task_id})["agent_config"]
    assert "angle" not in agent["params"]
    assert "sous l'angle ," in agent["brief"]["prompt"]


def test_stale_form_is_refused(client, created):
    client.put("/api/channels/foot-scoop-fr", json={**created, "name": "v2"})
    response = launch(client, channel_version=1)
    assert response.status_code == 409


def test_missing_avatar_is_caught_before_the_gpu(client, storage, created):
    del storage.objects["avatars/nova.mp4"]
    assert "channel.agent_config.avatar.avatar_url" in errors(launch(client))


def test_preview_shows_what_the_agent_receives(client, channel):
    preview = client.post("/api/render", json={"channel": channel, "values": {"angle": "la revanche"}}).json()
    assert preview["prompt"] == "Résume ${source_url} sous l'angle la revanche, en 45 secondes."
    assert preview["missing"] == ["source_url"]
    assert preview["user_message"].startswith("TÂCHE\nRésume")


def test_runs_list_and_queue(client, db, created):
    first, second = launch(client).json(), launch(client).json()
    assert second["queue_position"] == 2
    runs = client.get("/api/runs").json()
    assert [r["task_id"] for r in runs] == [second["task_id"], first["task_id"]]
    assert runs[1]["queue_position"] == 1 and "agent_config" not in runs[0]
    assert client.get("/api/queue").json() == {"pending": 2, "working": 0}
    assert len(client.get("/api/runs?channel_id=other").json()) == 0


def test_legacy_tasks_are_listed(client, db):
    db.tasks.insert_one({
        "task_id": "news_live_0917_020312", "status": "done", "created_at": datetime.now(UTC),
        "channel_config": {"channel_name": "hudex-foot", "email": "a@b.co"}, "error": None,
    })
    [run] = client.get("/api/runs").json()
    assert run["channel_label"] == "news_live" and run["channel_name"] == "hudex-foot"


def test_run_detail_signs_the_video(client, db, created):
    task_id = launch(client).json()["task_id"]
    db.tasks.update_one({"task_id": task_id}, {"$set": {
        "status": "done", "stage": "publication",
        "result": {"title": "Gyökeres, la revanche", "video_uri": "s3://mavg-object-storage/hudex-foot/2026-09-30/x/video.mp4"},
    }})
    run = client.get(f"/api/runs/{task_id}").json()
    assert run["title"] == "Gyökeres, la revanche" and run["has_video"]
    assert run["video_url"].endswith("?inline")
    assert run["download_url"].endswith("gyokeres-la-revanche.mp4")
    assert run["brief"]["prompt"].startswith("Résume https://")


def test_only_pending_runs_can_be_removed(client, db, created):
    task_id = launch(client).json()["task_id"]
    other = launch(client).json()["task_id"]
    db.tasks.update_one({"task_id": other}, {"$set": {"status": "working"}})
    assert client.delete(f"/api/runs/{task_id}").status_code == 204
    assert client.delete(f"/api/runs/{other}").status_code == 409
    assert client.delete("/api/runs/nope").status_code == 404


def test_gallery_joins_videos_and_runs(client, db, storage, created):
    task_id = launch(client).json()["task_id"]
    uri = f"hudex-foot/2026-09-30/gyokeres-la-revanche/{task_id}/video.mp4"
    storage.put(uri, kind="video/mp4")
    storage.put("hudex-diy/2026-09-17/etagere-en-caisses/video.mp4", kind="video/mp4")
    storage.put("hudex-diy/2026-09-17/etagere-en-caisses/description.txt", "Étagère en caisses, 15 €\n\nLa description.".encode())
    db.tasks.update_one({"task_id": task_id}, {"$set": {"result": {"title": "Gyökeres !", "video_uri": f"s3://mavg-object-storage/{uri}"}}})
    items = client.get("/api/gallery").json()
    assert len(items) == 2  # description.txt n'est pas une vidéo
    by_title = {i["title"]: i for i in items}
    assert by_title["Gyökeres !"]["task_id"] == task_id
    # Vidéo d'avant l'interface : son vrai titre vient de description.txt, accents compris.
    assert by_title["Étagère en caisses, 15 €"]["channel_name"] == "hudex-diy"


@pytest.mark.skipif(not (WORKER_REPO / "task_config.py").exists(), reason="repo mavg absent")
def test_schema_copy_matches_the_worker():
    assert filecmp.cmp(ROOT / "app" / "task_config.py", WORKER_REPO / "task_config.py"), (
        "app/task_config.py a divergé du worker : lancer scripts/sync_schema.sh"
    )
