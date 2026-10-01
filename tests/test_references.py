"""Les paramètres image : une référence de plus, ou l'image de l'avatar, choisie à chaque run."""

import io

import pytest
from conftest import BUCKET, errors

from app.params import coerce
from app.task_config import load_task

HERO = f"s3://{BUCKET}/references/herisson.png"
OVEN = f"s3://{BUCKET}/references/four.webp"


@pytest.fixture
def story(client, storage, channel):
    """Un channel d'histoires : la présentatrice raconte, le héros change à chaque run."""
    storage.put("references/herisson.png", kind="image/png")
    storage.put("references/four.webp", kind="image/webp")
    channel["parameters"] = [
        {"name": "idee", "type": "string", "required": True},
        {"name": "heros", "type": "image", "required": True, "description": "le héros de l'histoire"},
        {"name": "decor", "type": "image", "description": "la boutique"},
    ]
    channel["agent_config"]["brief"] = {"prompt": "Raconte ${idee} : ${heros} ouvre sa boutique.", "mood": ""}
    channel["agent_config"]["publication"] = {"must_include": []}
    response = client.post("/api/channels", json=channel)
    assert response.status_code == 201, response.text
    return response.json()["channel"]


def launch(client, values):
    return client.post("/api/channels/foot-scoop-fr/runs", json={"values": values})


def test_image_values_must_be_bucket_images():
    assert coerce("image", f" {HERO} ") == HERO
    for raw in (f"s3://{BUCKET}/avatars/nova.mp4", "https://cdn.example/h.png", "s3://autre/h.png", f"s3://{BUCKET}/../h.png"):
        with pytest.raises(ValueError):
            coerce("image", raw)


def test_images_become_references_with_a_subject_label(client, db, story, monkeypatch):
    task_id = launch(client, {"idee": "un hérisson boulanger", "heros": HERO, "decor": OVEN}).json()["task_id"]
    doc = db.tasks.find_one({"task_id": task_id}, {"_id": 0})
    agent = doc["agent_config"]
    assert agent["references"] == [
        {"name": "heros", "image_url": HERO, "description": "le héros de l'histoire"},
        {"name": "decor", "image_url": OVEN, "description": "la boutique"},
    ]
    # Dans le brief, l'image devient le label par lequel l'agent désigne le sujet.
    assert agent["brief"]["prompt"] == "Raconte un hérisson boulanger : <Subject 2> ouvre sa boutique."
    # Une adresse d'image n'a rien à faire dans « SUJET PRÉCIS » : elle n'y est pas.
    assert agent["params"] == {"idee": "un hérisson boulanger"}
    assert doc["run_params"]["heros"] == HERO
    monkeypatch.setenv("FOUNDRY_RESOURCE", "hudex")
    message = load_task(doc).agent_config.user_message()
    assert "- <Subject 3> (<Picture 3>) : decor — la boutique." in message


def test_an_optional_image_left_empty_is_omitted(client, db, story):
    task_id = launch(client, {"idee": "x", "heros": HERO}).json()["task_id"]
    assert [r["name"] for r in db.tasks.find_one({"task_id": task_id})["agent_config"]["references"]] == ["heros"]


def test_missing_or_foreign_images_are_caught_before_the_gpu(client, storage, story):
    del storage.objects["references/four.webp"]
    found = errors(launch(client, {"idee": "x", "heros": "https://cdn.example/h.png", "decor": OVEN}))
    assert "image du bucket" in found["values.heros"]
    assert "introuvable" in found["values.decor"]


def test_the_avatar_can_come_from_an_image_parameter(client, db, story):
    channel = {**story, "agent_config": {**story["agent_config"], "avatar": {**story["agent_config"]["avatar"], "avatar_url": "${heros}", "appearance": "${idee}"}}}
    channel["parameters"][1]["required"] = False
    response = client.put("/api/channels/foot-scoop-fr", json=channel)
    assert response.status_code == 200, response.text
    # Même facultatif, le paramètre qui fournit l'avatar est exigé au lancement.
    assert "avatar" in errors(launch(client, {"idee": "x"}))["values.heros"]

    task_id = launch(client, {"idee": "un hérisson", "heros": HERO}).json()["task_id"]
    agent = db.tasks.find_one({"task_id": task_id})["agent_config"]
    assert agent["avatar"]["avatar_url"] == HERO and agent["avatar"]["appearance"] == "un hérisson"
    assert agent["references"] == []
    assert agent["brief"]["prompt"].endswith(": <Subject 1> ouvre sa boutique.")


@pytest.mark.parametrize(
    ("mutate", "field", "message"),
    [
        (lambda c: c["agent_config"]["publication"].update(must_include=["${heros}"]), "agent_config.publication.must_include.0", "est une image"),
        (lambda c: c["agent_config"]["avatar"].update(appearance="${heros}"), "agent_config.avatar.appearance", "est une image"),
        (lambda c: c["agent_config"]["avatar"].update(avatar_url="${idee}"), "agent_config.avatar.avatar_url", "type image"),
        (lambda c: c["agent_config"]["avatar"].update(avatar_url=f"s3://{BUCKET}/${{heros}}.png"), "agent_config.avatar.avatar_url", "cité seul"),
        (lambda c: c["parameters"][2].update(default="https://cdn.example/h.png"), "parameters.2.default", "image du bucket"),
    ],
)
def test_image_citation_rules(client, story, mutate, field, message):
    mutate(story)
    found = errors(client.put("/api/channels/foot-scoop-fr", json=story))
    assert field in found, found
    assert message in found[field]


def test_an_uncited_image_is_not_a_warning(client, story):
    response = client.get("/api/channels/foot-scoop-fr").json()
    assert not any("decor" in w["msg"] for w in response["warnings"])


def test_preview_and_run_detail_show_the_references(client, story):
    draft = {key: value for key, value in story.items() if key not in ("version", "created_at", "updated_at")}
    preview = client.post("/api/render", json={"channel": draft, "values": {"heros": HERO}}).json()
    assert "<Subject 2> ouvre sa boutique" in preview["prompt"] and "RÉFÉRENCES VISUELLES" in preview["user_message"]
    task_id = launch(client, {"idee": "x", "heros": HERO}).json()["task_id"]
    [reference] = client.get(f"/api/runs/{task_id}").json()["references"]
    assert reference["label"] == "<Subject 2>" and reference["url"].endswith("references/herisson.png?inline")


def test_reference_upload_takes_images_only(client, storage):
    def send(filename):
        return client.post("/api/assets/references", files={"file": (filename, io.BytesIO(b"x"), "image/png")}, data={"name": "Hérisson boulanger"})

    first = send("h.png")
    assert first.status_code == 201, first.text
    assert first.json()["uri"] == f"s3://{BUCKET}/references/herisson-boulanger.png"
    assert send("h.png").json()["uri"].endswith("herisson-boulanger-2.png")
    assert send("clip.mp4").status_code == 422
    storage.put("avatars/nova.png", kind="image/png")
    assert [r["name"] for r in client.get("/api/assets/references").json()] == ["herisson-boulanger-2", "herisson-boulanger"]
