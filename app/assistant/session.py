"""Une conversation de l'onglet Assistant : le fil, le brouillon du channel, les cartes.

Rangée dans Mongo (`assistant_sessions`), pas en mémoire : le conteneur peut redémarrer
ou se dédoubler entre deux messages. Le fil est stocké en JSON (`messages_to_dict`), car
les arguments d'outils peuvent porter des clés que Mongo refuse (`$`, `.`).

Une conversation ne sert qu'une requête à la fois : `locked` la réserve le temps d'un
tour, de façon atomique, ce qui écarte le double envoi et le double clic sur une carte.
"""

import json
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException
from langchain_core.messages import BaseMessage, HumanMessage, messages_from_dict, messages_to_dict
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.collection import Collection

from app.channels import ChannelIn

LOCK_TTL = timedelta(minutes=10)
"""Un tour qui a planté sans rendre la main ne bloque la conversation que ce temps-là."""

CardKind = Literal["image", "voices", "channel", "runs"]


class Card(BaseModel):
    """Ce que l'agent propose et que seul un clic exécute."""

    id: str
    tool_call_id: str
    """L'appel d'outil qui l'a posée : la carte s'affiche à sa place dans le fil."""
    kind: CardKind
    status: Literal["open", "done", "failed", "cancelled"] = "open"
    payload: dict[str, Any]
    """Ce que le clic exécutera, figé quand la carte est posée."""
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class Reference(BaseModel):
    """Une image de référence déposée sur une carte : l'agent la cite par son URI."""

    name: str
    uri: str


@dataclass
class Session:
    id: str
    created_at: datetime
    updated_at: datetime
    title: str = ""
    messages: list[BaseMessage] = field(default_factory=list)
    draft: ChannelIn | None = None
    base_version: int | None = None
    """La version enregistrée du channel que le brouillon édite ; None : un channel neuf."""
    cards: list[Card] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)

    def card(self, card_id: str) -> Card:
        for card in self.cards:
            if card.id == card_id:
                return card
        raise HTTPException(404, "Carte introuvable dans cette conversation.")

    def add_card(self, kind: CardKind, payload: dict[str, Any], tool_call_id: str) -> Card:
        card = Card(id=secrets.token_hex(4), tool_call_id=tool_call_id, kind=kind, payload=payload)
        self.cards.append(card)
        return card

    def say(self, text: str) -> None:
        self.messages.append(HumanMessage(text))
        if not self.title:
            self.title = text.strip().splitlines()[0][:80]

    def note(self, text: str, image_uri: str | None = None) -> None:
        """Ce que le Studio dit à l'agent (le résultat d'un clic), dans le fil de l'utilisateur.

        Un `HumanMessage` et pas un message système : l'API refuse un système au milieu
        du fil. `image_uri` fait voir l'image à l'agent au tour suivant (`app/assistant/agent.py`).
        """
        extra: dict[str, Any] = {"note": True}
        if image_uri:
            extra["image_uri"] = image_uri
        self.messages.append(HumanMessage(f"[Studio] {text}", additional_kwargs=extra))

    def add_reference(self, name: str, uri: str) -> None:
        self.references = [reference for reference in self.references if reference.name != name]
        self.references.append(Reference(name=name, uri=uri))


def _now() -> datetime:
    return datetime.now(UTC)


def _fields(session: Session) -> dict[str, Any]:
    return {
        "title": session.title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "messages": json.dumps(messages_to_dict(session.messages), ensure_ascii=False),
        "draft": session.draft.model_dump(mode="json") if session.draft else None,
        "base_version": session.base_version,
        "cards": [card.model_dump(mode="json") for card in session.cards],
        "references": [reference.model_dump() for reference in session.references],
    }


def from_document(document: dict[str, Any]) -> Session:
    return Session(
        id=document["_id"],
        title=document.get("title", ""),
        created_at=document["created_at"],
        updated_at=document["updated_at"],
        messages=messages_from_dict(json.loads(document.get("messages") or "[]")),
        draft=ChannelIn.model_validate(document["draft"]) if document.get("draft") else None,
        base_version=document.get("base_version"),
        cards=[Card.model_validate(card) for card in document.get("cards", [])],
        references=[Reference.model_validate(item) for item in document.get("references", [])],
    )


def create(sessions: Collection, draft: ChannelIn | None = None, base_version: int | None = None) -> Session:
    now = _now()
    session = Session(id=secrets.token_hex(6), created_at=now, updated_at=now, draft=draft, base_version=base_version)
    sessions.insert_one({"_id": session.id, **_fields(session), "busy_since": None})
    return session


def load(sessions: Collection, session_id: str) -> Session:
    document = sessions.find_one({"_id": session_id})
    if document is None:
        raise HTTPException(404, "Conversation introuvable.")
    return from_document(document)


def save(sessions: Collection, session: Session) -> None:
    """Écrit la conversation, sans rendre la main : `locked` s'en charge."""
    session.updated_at = _now()
    sessions.update_one({"_id": session.id}, {"$set": _fields(session)})


@contextmanager
def locked(sessions: Collection, session_id: str) -> Iterator[Session]:
    """La conversation, réservée à cette requête jusqu'à la sortie du bloc.

    Ce qui n'a pas été passé à `save` avant la sortie est perdu : un tour qui échoue ne
    laisse ni demi-réponse, ni carte orpheline.
    """
    now = _now()
    document = sessions.find_one_and_update(
        {"_id": session_id, "$or": [{"busy_since": None}, {"busy_since": {"$lt": now - LOCK_TTL}}]},
        {"$set": {"busy_since": now}},
        return_document=ReturnDocument.AFTER,
    )
    if document is None:
        if sessions.count_documents({"_id": session_id}, limit=1):
            raise HTTPException(409, "L'assistant répond déjà dans cette conversation : attends sa réponse.")
        raise HTTPException(404, "Conversation introuvable.")
    try:
        yield from_document(document)
    finally:
        sessions.update_one({"_id": session_id}, {"$set": {"busy_since": None}})


def busy(sessions: Collection, session_id: str) -> bool:
    document = sessions.find_one({"_id": session_id}, {"busy_since": 1}) or {}
    since = document.get("busy_since")
    return since is not None and since >= _now() - LOCK_TTL
