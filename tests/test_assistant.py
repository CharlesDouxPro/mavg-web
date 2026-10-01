"""L'assistant : il construit un brouillon, pose des cartes, et seul un clic écrit.

Le modèle est un faux scripté : chaque test dit ce que « l'agent » répond, appel d'outil
par appel d'outil. Rien ne part vers Foundry, ni vers la vraie base, ni vers le bucket.
"""

import copy
import itertools
import json
from collections import deque
from datetime import UTC, datetime

import pytest
from conftest import BUCKET
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from pydantic import Field

from app.assistant import agent as assistant_agent
from app.assistant.agent import assistant_llm
from app.assistant.session import Session
from app.assistant.tools import Studio, build_tools
from app.channels import ChannelIn
from app.db import assistant_collection

AVATAR = f"s3://{BUCKET}/avatars/pico.png"
VOICE = f"s3://{BUCKET}/voices/fr/male/20-30/hugo.wav"
GUEST = f"s3://{BUCKET}/references/renard.png"

STORY = {
    "id": "herisson-boulanger",
    "name": "Pico le hérisson",
    "description": "Un hérisson boulanger raconte sa journée.",
    "channel_config": {"channel_name": "pico-boulanger", "email": "ops@example.com"},
    "parameters": [
        {"name": "idee", "type": "string", "required": True, "description": "la situation de l'épisode"},
        {"name": "invite", "type": "image", "description": "le client du jour"},
    ],
    "agent_config": {
        "language": "fr",
        "brief": {"prompt": "Micro-fiction. Pico parle face caméra dans chaque plan et raconte ${idee}.", "mood": "tendre"},
        "avatar": {"name": "Pico", "avatar_url": AVATAR, "description": "boulanger", "appearance": "a small stylized 3D hedgehog"},
    },
}


class Scripted(GenericFakeChatModel):
    """Le faux modèle : il rend les réponses scriptées dans l'ordre, et garde ce qu'il a reçu."""

    seen: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class Script:
    """Les réponses du faux modèle ; épuisé, il échoue plutôt que de reboucler."""

    def __init__(self):
        self.replies: deque = deque()
        self.ids = itertools.count(1)

    def __iter__(self):
        return self

    def __next__(self):
        if not self.replies:
            raise AssertionError("Le faux modèle n'a plus de réponse scriptée.")
        reply = self.replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        return reply

    def calls(self, *calls: tuple[str, dict], text: str = "") -> "Script":
        """Une réponse qui appelle des outils (en un seul message, comme Claude le fait)."""
        tool_calls = [{"name": name, "args": args, "id": f"call_{next(self.ids)}"} for name, args in calls]
        self.replies.append(AIMessage(content=text, tool_calls=tool_calls))
        return self

    def says(self, text: str) -> "Script":
        self.replies.append(AIMessage(content=text))
        return self


@pytest.fixture
def script():
    return Script()


@pytest.fixture
def model(script):
    return Scripted(messages=script, seen=[])


@pytest.fixture
def assistant(client, db, storage, model):
    client.app.dependency_overrides[assistant_collection] = lambda: db.assistant_sessions
    client.app.dependency_overrides[assistant_llm] = lambda: model
    storage.put("avatars/pico.png", kind="image/png")
    storage.put("voices/fr/male/20-30/hugo.wav", kind="audio/wav")
    storage.put(
        "voices/fr/male/20-30/hugo.json",
        json.dumps({"description": "voix chaude, un peu rieuse", "text": "Bonjour"}).encode(),
    )
    storage.put("references/renard.png", kind="image/png")
    return client


@pytest.fixture
def story(assistant):
    response = assistant.post("/api/channels", json=copy.deepcopy(STORY))
    assert response.status_code == 201, response.text
    return response.json()["channel"]


def start(client, **body) -> str:
    response = client.post("/api/assistant/sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def say(client, session_id: str, text: str):
    return client.post(f"/api/assistant/sessions/{session_id}/messages", json={"text": text})


def click(client, session_id: str, card: dict, **body):
    return client.post(f"/api/assistant/sessions/{session_id}/cards/{card['id']}", json=body)


def cards(view: dict) -> list[dict]:
    return [item["card"] for item in view["items"] if item["kind"] == "card"]


def tools_for(session: Session, db, storage) -> dict:
    return {t.name: t for t in build_tools(session, Studio(db.channels, db.tasks, storage))}


def run_tool(tool, args: dict) -> str:
    return tool.invoke({"type": "tool_call", "name": tool.name, "id": "call_x", "args": args}).content


def blank_session() -> Session:
    now = datetime.now(UTC)
    return Session(id="s", created_at=now, updated_at=now)


# --- Les outils, sur un brouillon ---


def test_draft_tools_build_a_channel_and_report_what_blocks(db, storage):
    session = blank_session()
    tools = tools_for(session, db, storage)
    run_tool(tools["set_identity"], {"channel_id": "herisson-boulanger", "name": "Pico", "language": "fr"})
    report = run_tool(tools["check_draft"], {})
    assert "channel_config.email" in report and "Bloquant" in report

    assert "Langue inconnue" in run_tool(tools["set_identity"], {"language": "xx"})
    assert "impossible" in run_tool(
        tools["set_format"], {"min_total_seconds": 50, "max_total_seconds": 52, "min_shot_seconds": 9, "max_shot_seconds": 9}
    )
    run_tool(tools["set_format"], {"arc": ["hook", "situation", "chute"], "min_total_seconds": 20, "max_total_seconds": 40,
                                    "min_shot_seconds": 5, "max_shot_seconds": 9})
    assert session.draft.agent_config.plan.arc == ["hook", "situation", "chute"]

    # Des plans muets, mais jamais tous : au moins un plan parle.
    assert "Plans muets : entre 0 et 7" in run_tool(tools["set_format"], {"max_silent_shots": 8})
    run_tool(tools["set_format"], {"max_silent_shots": 1})
    assert session.draft.agent_config.plan.max_silent_shots == 1
    assert "plans muets : 1 au plus" in run_tool(tools["check_draft"], {})


def test_propose_channel_refuses_until_the_draft_is_complete(db, storage):
    session = blank_session()
    tools = tools_for(session, db, storage)
    draft = copy.deepcopy(STORY)
    draft["agent_config"]["avatar"]["appearance"] = ""
    session.draft = ChannelIn.model_validate(draft)
    refused = run_tool(tools["propose_channel"], {})
    assert "appearance" in refused and not session.cards

    run_tool(tools["set_avatar"], {"appearance_en": "a small stylized 3D hedgehog with a white apron"})
    assert "Carte posée" in run_tool(tools["propose_channel"], {})
    [card] = session.cards
    assert card.kind == "channel" and card.payload["base_version"] is None
    # Poser une carte n'écrit rien.
    assert db.channels.count_documents({}) == 0


def test_voices_and_images_must_come_from_the_bucket(db, storage, assistant):
    session = blank_session()
    session.draft = ChannelIn.model_validate(copy.deepcopy(STORY))
    tools = tools_for(session, db, storage)
    found = run_tool(tools["find_voices"], {"language": "fr"})
    assert "hugo" in found and "voix chaude" in found
    assert "pas dans le catalogue" in run_tool(tools["set_voice"], {"voice_uri": f"s3://{BUCKET}/voices/fr/male/20-30/inconnu.wav"})
    run_tool(tools["set_voice"], {"voice_uri": VOICE})
    assert session.draft.agent_config.avatar.voice_url == VOICE
    assert "introuvable" in run_tool(tools["set_avatar"], {"avatar_uri": f"s3://{BUCKET}/avatars/absent.png"})
    assert "Pas dans le catalogue" in run_tool(tools["suggest_voices"], {"voice_uris": ["s3://x/y.wav"], "why": "."})


# --- La conversation, de bout en bout ---


def test_a_conversation_drafts_then_saves_on_click_only(assistant, db, script, model):
    session_id = start(assistant)
    draft = copy.deepcopy(STORY)
    # Un appel mal formé revient au modèle en erreur, sans casser le tour.
    script.calls(("set_brief", {"parameters": [{"name": "idee", "type": "video"}]}))
    script.calls(
        ("set_identity", {"channel_id": draft["id"], "name": draft["name"], "description": draft["description"],
                          "language": "fr", "channel_name": "pico-boulanger", "email": "ops@example.com"}),
        ("set_brief", {"prompt": draft["agent_config"]["brief"]["prompt"], "mood": "tendre", "parameters": draft["parameters"]}),
        ("set_avatar", {"name": "Pico", "appearance_en": "a small stylized 3D hedgehog", "avatar_uri": AVATAR}),
    ).calls(("propose_channel", {})).says("Voici le channel, il ne reste qu'à l'enregistrer.")

    response = say(assistant, session_id, "Je veux une chaîne sur un hérisson boulanger")
    assert response.status_code == 200, response.text
    view = response.json()
    [card] = cards(view)
    assert card["kind"] == "channel" and card["status"] == "open"
    assert view["items"][0] == {"kind": "user", "text": "Je veux une chaîne sur un hérisson boulanger"}
    assert view["items"][-1]["text"] == "Voici le channel, il ne reste qu'à l'enregistrer."
    assert view["draft"]["id"] == "herisson-boulanger"
    assert db.channels.count_documents({}) == 0  # l'agent n'a rien écrit
    refused = model.seen[1][-1]
    assert refused.type == "tool" and "video" in refused.text and refused.status == "error"

    script.says("C'est enregistré.")
    view = click(assistant, session_id, card, action="confirm").json()
    stored = db.channels.find_one({"_id": "herisson-boulanger"})
    assert stored["version"] == 1
    assert view["base_version"] == 1 and cards(view)[0]["status"] == "done"
    note = [item for item in view["items"] if item["kind"] == "note"][-1]
    assert "enregistré (version 1)" in note["text"]
    # L'agent a reçu la note avant de répondre.
    assert "[Studio] Channel herisson-boulanger enregistré" in model.seen[-1][-1].text

    # Une retouche ensuite enregistre la version 2, par un PUT.
    script.calls(("set_identity", {"description": "Pico raconte sa boulangerie."})).calls(("propose_channel", {})).says("Prêt.")
    view = say(assistant, session_id, "Change la description").json()
    second = cards(view)[-1]
    assert second["payload"]["base_version"] == 1
    script.says("Version 2.")
    click(assistant, session_id, second, action="confirm")
    assert db.channels.find_one({"_id": "herisson-boulanger"})["version"] == 2

    # Un second clic sur une carte jouée ne refait rien.
    again = click(assistant, session_id, second, action="confirm")
    assert again.status_code == 409


def test_runs_are_proposed_then_only_the_checked_ones_are_queued(assistant, db, story, script):
    session_id = start(assistant, channel_id="herisson-boulanger")
    ideas = [{"pitch": f"Idée {n}", "values": {"idee": f"la fournée numéro {n}"}} for n in range(1, 4)]
    ideas[1]["values"]["invite"] = GUEST
    script.calls(("propose_runs", {"channel_id": "herisson-boulanger", "candidates": [
        {"pitch": "Une idée", "values": {"idee": "x", "inconnu": "y"}},
        {"pitch": "Une autre", "values": {"idee": "x", "invite": f"s3://{BUCKET}/references/absente.png"}},
    ]})).calls(("propose_runs", {"channel_id": "herisson-boulanger", "candidates": ideas})).says("Coche ceux que tu veux.")

    view = say(assistant, session_id, "Propose 3 runs").json()
    # Le premier appel a été refusé (paramètre inconnu, image absente) : une seule carte.
    [card] = cards(view)
    assert [c["n"] for c in card["payload"]["candidates"]] == [1, 2, 3]
    assert card["payload"]["channel_version"] == story["version"]
    assert db.tasks.count_documents({}) == 0

    script.says("Deux runs partent.")
    view = click(assistant, session_id, card, action="confirm", selected=[1, 2]).json()
    tasks = list(db.tasks.find({}, {"_id": 0}))
    assert len(tasks) == 2 and {t["status"] for t in tasks} == {"pending"}
    assert sorted(t["run_params"]["idee"] for t in tasks) == ["la fournée numéro 1", "la fournée numéro 2"]
    guest = next(t for t in tasks if "invite" in t["run_params"])
    assert guest["agent_config"]["references"][0]["image_url"] == GUEST
    runs = cards(view)[0]["result"]["runs"]
    assert [r["n"] for r in runs] == [1, 2] and all("task_id" in r for r in runs)


def test_a_stale_channel_version_shows_in_the_card(assistant, db, story, script):
    session_id = start(assistant, channel_id="herisson-boulanger")
    script.calls(("propose_runs", {"channel_id": "herisson-boulanger", "candidates": [
        {"pitch": "Idée", "values": {"idee": "le pain brûlé"}}]})).says("Voilà.")
    [card] = cards(say(assistant, session_id, "Un run").json())
    # Le channel est modifié dans l'éditeur entre-temps.
    edit = {**story, "name": "Pico v2"}
    assert assistant.put("/api/channels/herisson-boulanger", json=edit).status_code == 200

    script.says("Le channel a changé.")
    view = click(assistant, session_id, card, action="confirm", selected=[1]).json()
    [run] = cards(view)[0]["result"]["runs"]
    assert "modifié" in run["error"] and db.tasks.count_documents({}) == 0


def test_an_attached_avatar_is_shown_to_the_agent(assistant, script, model, monkeypatch):
    monkeypatch.setattr(assistant_agent, "read_image", lambda storage, key, limit=0: b"\x89PNG")
    session_id = start(assistant)
    script.calls(("request_image", {"purpose": "avatar", "name": "Pico", "prompt_en": "A small hedgehog baker, 9:16",
                                     "why": "le héros"})).says("Génère l'image et dépose-la.")
    [card] = cards(say(assistant, session_id, "Fais-moi Pico").json())
    assert card["payload"]["prompt"].startswith("A small hedgehog")

    assert click(assistant, session_id, card, action="attach", uri=f"s3://{BUCKET}/avatars/absent.png").status_code == 422
    script.says("Je le vois : un petit hérisson.")
    view = click(assistant, session_id, card, action="attach", uri=AVATAR).json()
    assert view["draft"]["agent_config"]["avatar"]["avatar_url"] == AVATAR
    assert view["draft"]["agent_config"]["avatar"]["name"] == "Pico"
    sent = model.seen[-1][-1]
    assert sent.content[1]["type"] == "image" and sent.content[1]["mime_type"] == "image/png"
    # En base, la note ne garde que l'URI.
    assert "base64" not in assistant.app.dependency_overrides[assistant_collection]().find_one()["messages"]


def test_a_failed_turn_keeps_the_message_and_frees_the_conversation(assistant, db, script):
    session_id = start(assistant)
    script.replies.append(RuntimeError("Foundry injoignable"))
    response = say(assistant, session_id, "Bonjour")
    assert response.status_code == 502 and "Foundry injoignable" in response.json()["detail"]
    view = assistant.get(f"/api/assistant/sessions/{session_id}").json()
    assert [item["kind"] for item in view["items"]] == ["user"] and not view["busy"]

    # Relancer sans texte rejoue le tour sur le message resté sans réponse.
    script.says("Bonjour ! On crée quoi ?")
    view = say(assistant, session_id, "").json()
    assert [item["kind"] for item in view["items"]] == ["user", "assistant"]


def test_a_busy_conversation_refuses_a_second_request(assistant, db):
    session_id = start(assistant)
    db.assistant_sessions.update_one({"_id": session_id}, {"$set": {"busy_since": datetime.now(UTC)}})
    assert say(assistant, session_id, "Bonjour").status_code == 409


def test_without_foundry_keys_the_assistant_says_so(client, db, monkeypatch):
    client.app.dependency_overrides[assistant_collection] = lambda: db.assistant_sessions
    monkeypatch.delenv("FOUNDRY_RESOURCE", raising=False)
    monkeypatch.delenv("FOUNDRY_API_KEY", raising=False)
    session_id = client.post("/api/assistant/sessions", json={}).json()["id"]
    response = say(client, session_id, "Bonjour")
    assert response.status_code == 503 and "FOUNDRY_API_KEY" in response.json()["detail"]
