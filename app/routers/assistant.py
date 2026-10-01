"""L'onglet Assistant : une conversation qui prépare un channel et propose des runs.

Chaque route renvoie la vue de la conversation (`view`), jamais les messages bruts du
modèle. Les routes sont synchrones : un tour de l'assistant dure des dizaines de secondes
et tourne dans le pool de threads, sans bloquer la boucle du serveur.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from app.assistant import session as conversations
from app.assistant.actions import CardAction, execute
from app.assistant.agent import TurnFailed, assistant_llm, run_turn
from app.assistant.session import Card, Session
from app.assistant.tools import Studio, as_draft, load_channel, voice_catalog, voice_sheet
from app.deps import Channels, MaybeStorage, Sessions, Tasks
from app.storage import VIDEO_TYPES, Storage, bucket_key

log = logging.getLogger("mavg-web")
router = APIRouter(prefix="/api/assistant", tags=["assistant"])

LLM = Annotated[BaseChatModel, Depends(assistant_llm)]


class StartRequest(BaseModel):
    channel_id: str | None = None
    """Ouvrir la conversation sur un channel enregistré, pour le retoucher ou y lancer des runs."""


class MessageRequest(BaseModel):
    text: str = ""
    """Vide : relance le dernier tour, s'il a échoué."""


def _link(storage: Storage | None, uri: str) -> str | None:
    key = bucket_key(uri or "")
    return storage.link(key) if storage is not None and key else None


def _media(storage: Storage | None, uri: str) -> dict | None:
    if not uri:
        return None
    kind = "video" if (bucket_key(uri) or "").lower().endswith(tuple(VIDEO_TYPES)) else "image"
    return {"uri": uri, "url": _link(storage, uri), "kind": kind}


def _voices(storage: Storage | None, uris: list[str]) -> list[dict]:
    catalog = voice_catalog(storage)
    shown = []
    for uri in uris:
        voice = catalog.get(uri)
        if voice is None:
            shown.append({"uri": uri, "name": uri.rsplit("/", 1)[-1], "missing": True})
            continue
        sheet = voice_sheet(storage, uri) if storage is not None else {}
        shown.append({**voice, "description": sheet.get("description", ""), "text": sheet.get("text", "")})
    return shown


def _card(card: Card, storage: Storage | None) -> dict:
    shown: dict[str, Any] = card.model_dump(mode="json", exclude={"tool_call_id"})
    if card.kind == "image" and card.result.get("uri"):
        shown["result"]["media"] = _media(storage, card.result["uri"])
    elif card.kind == "voices":
        shown["voices"] = _voices(storage, card.payload["uris"])
    elif card.kind == "channel":
        avatar = card.payload["channel"]["agent_config"]["avatar"]
        shown["avatar"] = _media(storage, avatar.get("avatar_url", ""))
        shown["voice"] = (_voices(storage, [avatar["voice_url"]]) or [None])[0] if avatar.get("voice_url") else None
    return shown


def view(session: Session, storage: Storage | None, busy: bool = False) -> dict:
    """La conversation telle que la page l'affiche : le fil, les cartes à leur place, le brouillon."""
    cards = {card.tool_call_id: card for card in session.cards}
    items: list[dict] = []
    for message in session.messages:
        if isinstance(message, HumanMessage):
            kind = "note" if message.additional_kwargs.get("note") else "user"
            items.append({"kind": kind, "text": message.text.removeprefix("[Studio] ")})
        elif isinstance(message, AIMessage):
            if message.text.strip():
                items.append({"kind": "assistant", "text": message.text.strip()})
        elif isinstance(message, ToolMessage) and (card := cards.get(message.tool_call_id)):
            items.append({"kind": "card", "card": _card(card, storage)})
    avatar = session.draft.agent_config.avatar if session.draft else None
    return {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "base_version": session.base_version,
        "draft": session.draft.model_dump(mode="json") if session.draft else None,
        "draft_media": {
            "avatar": _media(storage, avatar.avatar_url) if avatar else None,
            "voice": (_voices(storage, [avatar.voice_url]) or [None])[0] if avatar and avatar.voice_url else None,
        },
        "references": [
            {**reference.model_dump(), "url": _link(storage, reference.uri)} for reference in session.references
        ],
        "items": items,
        "busy": busy,
    }


def _turn(session: Session, llm: BaseChatModel, studio: Studio, sessions: Sessions) -> None:
    try:
        run_turn(session, llm, studio)
    except TurnFailed as exc:
        log.warning("Assistant %s : %s", session.id, exc.__cause__ or exc)
        raise HTTPException(502, str(exc)) from None
    conversations.save(sessions, session)


@router.get("/sessions")
def list_sessions(sessions: Sessions) -> list[dict]:
    cursor = sessions.find({}, {"title": 1, "updated_at": 1, "draft.id": 1, "draft.name": 1}).sort("updated_at", -1)
    return [
        {
            "id": document["_id"],
            "title": document.get("title") or "Nouvelle conversation",
            "updated_at": document.get("updated_at"),
            "channel_id": (document.get("draft") or {}).get("id") or None,
            "channel_name": (document.get("draft") or {}).get("name") or None,
        }
        for document in cursor.limit(30)
    ]


@router.post("/sessions", status_code=201)
def start(body: StartRequest, sessions: Sessions, channels: Channels, tasks: Tasks, storage: MaybeStorage) -> dict:
    if body.channel_id is None:
        return view(conversations.create(sessions), storage)
    channel = load_channel(Studio(channels, tasks, storage), body.channel_id)
    if channel is None:
        raise HTTPException(404, f"Channel {body.channel_id} introuvable.")
    session = conversations.create(sessions, draft=as_draft(channel), base_version=channel.version)
    return view(session, storage)


@router.get("/sessions/{session_id}")
def get_session(session_id: str, sessions: Sessions, storage: MaybeStorage) -> dict:
    return view(conversations.load(sessions, session_id), storage, conversations.busy(sessions, session_id))


@router.post("/sessions/{session_id}/messages")
def send(
    session_id: str, body: MessageRequest, sessions: Sessions, channels: Channels, tasks: Tasks, storage: MaybeStorage, llm: LLM
) -> dict:
    with conversations.locked(sessions, session_id) as session:
        text = body.text.strip()
        if text:
            session.say(text)
            # Enregistré avant l'appel : un tour qui échoue ne fait pas perdre le message.
            conversations.save(sessions, session)
        elif not session.messages or not isinstance(session.messages[-1], HumanMessage):
            raise HTTPException(422, "Message vide.")
        _turn(session, llm, Studio(channels, tasks, storage), sessions)
    return view(session, storage)


@router.post("/sessions/{session_id}/cards/{card_id}")
def act(
    session_id: str,
    card_id: str,
    body: CardAction,
    sessions: Sessions,
    channels: Channels,
    tasks: Tasks,
    storage: MaybeStorage,
    llm: LLM,
) -> dict:
    studio = Studio(channels, tasks, storage)
    with conversations.locked(sessions, session_id) as session:
        execute(session, session.card(card_id), body, studio)
        # Ce qui a été écrit (channel, runs) est rangé avant que l'agent ne réagisse.
        conversations.save(sessions, session)
        _turn(session, llm, studio, sessions)
    return view(session, storage)
