"""Les channels : création, édition versionnée, et ce que la validation refuse."""

import pytest
from conftest import errors


def test_create_stores_a_sparse_document_without_secrets(client, db, created):
    assert created["version"] == 1
    stored = db.channels.find_one({"_id": "foot-scoop-fr"})
    agent = stored["agent_config"]
    # Rien de ce que le serveur remplit lui-même : ni adresse, ni clé, ni défaut.
    assert "render" not in agent and "llm" not in agent
    text = str(stored)
    assert "base_url" not in text and "token" not in text and "FOUNDRY" not in text


def test_get_returns_defaults_filled_in(client, created):
    channel = client.get("/api/channels/foot-scoop-fr").json()["channel"]
    assert channel["agent_config"]["render"]["seed"] == 42
    assert channel["agent_config"]["models"]["video_generator"]["provider"] == "sglang"


def test_list_shows_avatar_preview_and_run_count(client, created):
    [summary] = client.get("/api/channels").json()
    assert summary["avatar"]["kind"] == "video" and summary["avatar"]["url"].startswith("https://signed")
    assert summary["runs"] == 0 and summary["parameters"] == ["source_url", "angle", "duree"]


def test_duplicate_id_is_refused(client, channel, created):
    assert client.post("/api/channels", json=channel).status_code == 409


def test_update_bumps_version_and_refuses_stale_edits(client, created):
    edit = {**created, "name": "Foot v2"}
    response = client.put("/api/channels/foot-scoop-fr", json=edit)
    assert response.status_code == 200, response.text
    assert response.json()["channel"]["version"] == 2
    # Un second onglet encore en version 1 ne peut pas écraser la version 2.
    stale = client.put("/api/channels/foot-scoop-fr", json={**created, "name": "Foot v1 bis"})
    assert stale.status_code == 409 and "version 2" in stale.json()["detail"]


def test_id_cannot_change_on_update(client, created):
    assert "id" in errors(client.put("/api/channels/foot-scoop-fr", json={**created, "id": "other"}))


def test_delete_requires_current_version(client, created):
    assert client.delete("/api/channels/foot-scoop-fr?version=9").status_code == 409
    assert client.delete("/api/channels/foot-scoop-fr?version=1").status_code == 204
    assert client.get("/api/channels/foot-scoop-fr").status_code == 404


def test_worker_machine_settings_are_reset(client, channel):
    channel["agent_config"]["render"] = {"output_dir": "/etc", "seed": 7}
    channel["agent_config"]["subtitles"] = {"ffmpeg_bin": "/bin/sh"}
    agent = client.post("/api/channels", json=channel).json()["channel"]["agent_config"]
    assert agent["render"]["output_dir"] == "runs" and agent["render"]["seed"] == 7
    assert agent["subtitles"]["ffmpeg_bin"] == ""


def test_unused_parameter_is_only_a_warning(client, channel):
    channel["parameters"].append({"name": "bonus", "type": "string"})
    response = client.post("/api/channels", json=channel)
    assert response.status_code == 201
    assert any("bonus" in w["msg"] for w in response.json()["warnings"])


@pytest.mark.parametrize(
    ("mutate", "field", "message"),
    [
        (lambda c: c["agent_config"]["brief"].update(prompt="Parle de ${inconnu}"), "agent_config.brief.prompt", "pas déclaré"),
        (lambda c: c["agent_config"]["brief"].update(prompt="Parle de ${Source}"), "agent_config.brief.prompt", "minuscules"),
        (lambda c: c["agent_config"]["brief"].update(prompt="Parle de ${source_url"), "agent_config.brief.prompt", "${nom}"),
        (lambda c: c.update(description="${source_url}"), "description", "n'est remplacé que"),
        (lambda c: c["channel_config"].update(email="pas-un-email"), "channel_config.email", "e-mail"),
        (lambda c: c.update(id="Pas Un Slug"), "id", "minuscules"),
        (lambda c: c["parameters"].append({"name": "Mauvais-Nom"}), "parameters.3.name", "Minuscules"),
        (lambda c: c["parameters"].append({"name": "angle"}), "parameters.3.name", "Deux paramètres"),
        (lambda c: c["parameters"][2].update(default="beaucoup"), "parameters.2.default", "nombre"),
        (lambda c: c["agent_config"]["avatar"].update(avatar_url="http://169.254.42.42/x.png"), "agent_config.avatar.avatar_url", "bucket"),
        (lambda c: c["agent_config"]["avatar"].update(voice_url="s3://autre-bucket/v.wav"), "agent_config.avatar.voice_url", "bucket"),
        (lambda c: c["agent_config"].update(models={"slm": {"provider": "evil", "model_name": "x"}}), "agent_config.models.slm.provider", "inconnu"),
        (lambda c: c["agent_config"].update(language="xx"), "agent_config.language", "Langue"),
    ],
)
def test_validation_rules(client, channel, mutate, field, message):
    mutate(channel)
    found = errors(client.post("/api/channels", json=channel))
    assert field in found, found
    assert message in found[field]


def test_secrets_cannot_be_smuggled_in(client, channel):
    # Le channel n'a pas de champ base_url / token : le schéma les refuse.
    channel["agent_config"]["models"] = {
        "slm": {"provider": "foundry", "model_name": "x", "base_url": "https://attacker.example/"}
    }
    assert client.post("/api/channels", json=channel).status_code == 422


def test_catalog_lists_what_the_editor_offers(client):
    catalog = client.get("/api/catalog").json()
    assert catalog["skills"][0]["name"] == "tiktok-news-article-presentation"
    assert {p["id"] for p in catalog["providers"]} == {"foundry", "sglang"}
    assert catalog["languages"]["fr"] == "French"
    assert "Clips en vol" in catalog["help"]["RenderSettings"]["concurrency"]
    assert catalog["storage"] is True
