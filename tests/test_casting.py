"""Des runs sans image : le réalisateur invente les personnages (`plan.max_characters`)."""

import pytest
from conftest import BUCKET, errors

from app.task_config import load_task

HERO = f"s3://{BUCKET}/references/herisson.png"
NO_AVATAR = {"name": "", "avatar_url": "", "description": "", "appearance": ""}


def launch(client, values):
    return client.post("/api/channels/foot-scoop-fr/runs", json={"values": values})


@pytest.fixture
def fiction(channel):
    """Une micro-fiction : une idée par run, et une image du héros quand on en a une."""
    channel["parameters"] = [
        {"name": "idee", "type": "string", "required": True},
        {"name": "heros", "type": "image", "description": "le héros, s'il y a une image"},
    ]
    channel["agent_config"]["brief"] = {"prompt": "Raconte ${idee} : ${heros} ouvre sa boutique.", "mood": ""}
    channel["agent_config"]["publication"] = {"must_include": []}
    channel["agent_config"]["plan"] = {"max_characters": 2}
    return channel


def saved(client, channel) -> list[dict]:
    response = client.post("/api/channels", json=channel)
    assert response.status_code == 201, response.text
    return response.json()["warnings"]


def test_a_channel_without_avatar_runs_with_invented_characters(client, db, fiction, monkeypatch):
    fiction["parameters"].pop()
    fiction["agent_config"]["brief"]["prompt"] = "Raconte ${idee}."
    fiction["agent_config"]["avatar"] = NO_AVATAR
    assert not [w for w in saved(client, fiction) if "avatar" in w["msg"]]

    response = launch(client, {"idee": "un hérisson boulanger"})
    assert response.status_code == 201, response.text
    doc = db.tasks.find_one({"task_id": response.json()["task_id"]}, {"_id": 0})
    assert doc["agent_config"]["avatar"] is None

    monkeypatch.setenv("LLM_BASE_URL", "http://llm:30000")
    message = load_task(doc).agent_config.user_message()
    assert "CASTING" in message and "Cette chaîne n'a pas d'avatar" in message


def test_without_avatar_nor_casting_nothing_launches(client, fiction):
    fiction["agent_config"]["avatar"] = NO_AVATAR
    fiction["agent_config"]["plan"] = {"max_characters": 0}
    assert any("inventer les personnages" in w["msg"] for w in saved(client, fiction))
    found = errors(launch(client, {"idee": "x"}))
    assert "inventer les personnages" in found["channel.agent_config.avatar.avatar_url"]


def test_the_avatar_image_can_be_left_out_of_a_run(client, db, storage, fiction):
    storage.put("references/herisson.png", kind="image/png")
    fiction["agent_config"]["avatar"] = {**NO_AVATAR, "avatar_url": "${heros}"}
    saved(client, fiction)

    without = launch(client, {"idee": "un hérisson"}).json()["task_id"]
    agent = db.tasks.find_one({"task_id": without})["agent_config"]
    # Le personnage principal inventé prend la place de l'avatar : le brief le cite pareil.
    assert agent["avatar"] is None
    assert agent["brief"]["prompt"] == "Raconte un hérisson : <Subject 1> ouvre sa boutique."

    with_image = launch(client, {"idee": "un hérisson", "heros": HERO}).json()["task_id"]
    assert db.tasks.find_one({"task_id": with_image})["agent_config"]["avatar"]["avatar_url"] == HERO


def test_a_required_avatar_image_stays_required(client, fiction):
    fiction["parameters"][1]["required"] = True
    fiction["agent_config"]["avatar"] = {**NO_AVATAR, "avatar_url": "${heros}"}
    saved(client, fiction)
    assert errors(launch(client, {"idee": "x"}))["values.heros"] == "Paramètre requis."


def test_the_preview_shows_the_casting(client, fiction):
    fiction["agent_config"]["avatar"] = NO_AVATAR
    preview = client.post("/api/render", json={"channel": fiction, "values": {"idee": "un hérisson"}}).json()
    assert "CASTING" in preview["user_message"]
