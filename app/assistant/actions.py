"""Ce que fait un clic sur une carte : le seul chemin par lequel l'assistant écrit.

Chaque action passe par les routes du Studio, appelées comme de simples fonctions
(`create_channel`, `update_channel`, `launch_run`) : mêmes contrôles, même verrou de
version, même tâche construite que depuis l'éditeur. Ce qui est exécuté est la charge
de la carte, figée quand l'agent l'a posée.

Une carte ne sert qu'une fois. La conversation étant réservée pendant le clic
(`session.locked`), un double clic trouve la carte déjà jouée et ne relance rien.
"""

from pathlib import PurePosixPath
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.assistant.session import Card, Session
from app.assistant.tools import (
    STUDIO_ERRORS,
    Studio,
    as_draft,
    blank_channel,
    explain,
    voice_catalog,
)
from app.channels import ChannelIn, ChannelUpdate
from app.routers.channels import LaunchRequest, create_channel, launch_run, update_channel
from app.storage import IMAGE_TYPES, VIDEO_TYPES, bucket_key


class CardAction(BaseModel):
    action: Literal["attach", "choose", "confirm", "cancel"]
    uri: str = ""
    """L'image déposée (`attach`) ou la voix choisie (`choose`)."""
    selected: list[int] = Field(default_factory=list)
    """Les numéros des runs cochés (`confirm` d'une carte de runs)."""


EXPECTED = {"image": "attach", "voices": "choose", "channel": "confirm", "runs": "confirm"}
LABEL = {"image": "image", "voices": "voix", "channel": "channel", "runs": "runs"}


def execute(session: Session, card: Card, body: CardAction, studio: Studio) -> None:
    """Joue la carte et laisse une note à l'agent. Lève 409 / 422 sans rien avoir écrit."""
    if card.status != "open":
        raise HTTPException(409, "Cette carte a déjà servi.")
    if body.action == "cancel":
        card.status = "cancelled"
        session.note(f"L'utilisateur a écarté la carte {LABEL[card.kind]}. Demande-lui ce qui ne va pas.")
        return
    if body.action != EXPECTED[card.kind]:
        raise HTTPException(422, f"Action {body.action} impossible sur une carte {LABEL[card.kind]}.")
    {"image": _attach, "voices": _choose, "channel": _save, "runs": _launch}[card.kind](session, card, body, studio)


def _attach(session: Session, card: Card, body: CardAction, studio: Studio) -> None:
    purpose, name = card.payload["purpose"], card.payload["name"]
    uri = body.uri.strip()
    key = bucket_key(uri)
    kinds = {**IMAGE_TYPES, **VIDEO_TYPES} if purpose == "avatar" else IMAGE_TYPES
    suffix = PurePosixPath(key or "").suffix.lower()
    if key is None or suffix not in kinds:
        raise HTTPException(422, f"Attendu : un fichier du bucket ({', '.join(sorted(kinds))}).")
    if studio.storage is not None and not studio.storage.exists(key):
        raise HTTPException(422, f"{uri} est introuvable dans le bucket.")

    if purpose == "avatar":
        draft = session.draft or blank_channel()
        avatar = draft.agent_config.avatar.model_copy(
            update={"avatar_url": uri, "reference_frame_s": None, "name": draft.agent_config.avatar.name or name}
        )
        agent = draft.agent_config.model_copy(update={"avatar": avatar})
        session.draft = draft.model_copy(update={"agent_config": agent})
        hint = "Regarde-la, puis écris son apparence en anglais avec set_avatar et montre-la à l'utilisateur."
    else:
        session.add_reference(name, uri)
        hint = "Elle peut servir de valeur à un paramètre image d'un run."
    card.status, card.result = "done", {"uri": uri}
    # Une vidéo ne se montre pas au modèle : il demandera à l'utilisateur de la décrire.
    seen = uri if suffix in IMAGE_TYPES else None
    session.note(
        f"Image déposée pour « {name} » ({purpose}) : {uri}. "
        + (hint if seen else "C'est une vidéo, tu ne peux pas la voir : demande à l'utilisateur de la décrire."),
        image_uri=seen,
    )


def _choose(session: Session, card: Card, body: CardAction, studio: Studio) -> None:
    voice = voice_catalog(studio.storage).get(body.uri.strip())
    if voice is None:
        raise HTTPException(422, "Cette voix n'est pas dans le catalogue.")
    draft = session.draft or blank_channel()
    avatar = draft.agent_config.avatar.model_copy(update={"voice_url": voice["uri"]})
    session.draft = draft.model_copy(update={"agent_config": draft.agent_config.model_copy(update={"avatar": avatar})})
    card.status, card.result = "done", {"uri": voice["uri"]}
    session.note(f"Voix choisie : {voice['name']} ({voice['language']}, {voice['sex']}, {voice['age_range']}) — {voice['uri']}.")


def _save(session: Session, card: Card, body: CardAction, studio: Studio) -> None:
    channel = ChannelIn.model_validate(card.payload["channel"])
    base = card.payload["base_version"]
    try:
        if base is None:
            saved = create_channel(channel, studio.channels)
        else:
            update = ChannelUpdate.model_validate({**channel.model_dump(), "version": base})
            saved = update_channel(channel.id, update, studio.channels)
    except STUDIO_ERRORS as exc:
        card.status, card.error = "failed", explain(exc)
        session.note(f"Enregistrement refusé : {card.error}")
        return
    stored = saved["channel"]
    warnings = [str(item.get("msg", "")) for item in saved["warnings"]]
    card.status = "done"
    card.result = {"channel_id": stored.id, "version": stored.version, "warnings": warnings}
    # Les retouches faites dans le fil depuis la carte restent dans le brouillon ; il édite
    # désormais cette version-ci.
    session.base_version = stored.version
    if session.draft is None or session.draft.id != stored.id:
        session.draft = as_draft(stored)
    session.note(
        f"Channel {stored.id} enregistré (version {stored.version})."
        + (f" Avertissements : {' ; '.join(warnings)}" if warnings else "")
    )


def _launch(session: Session, card: Card, body: CardAction, studio: Studio) -> None:
    candidates = {candidate["n"]: candidate for candidate in card.payload["candidates"]}
    selected = sorted(set(body.selected))
    if not selected:
        raise HTTPException(422, "Coche au moins un run.")
    unknown = [n for n in selected if n not in candidates]
    if unknown:
        raise HTTPException(422, f"Runs inconnus : {unknown}.")

    results = []
    for n in selected:
        request = LaunchRequest(values=candidates[n]["values"], channel_version=card.payload["channel_version"])
        try:
            launched = launch_run(card.payload["channel_id"], request, studio.channels, studio.tasks, studio.storage)
        except STUDIO_ERRORS as exc:
            results.append({"n": n, "error": explain(exc)})
            continue
        results.append({"n": n, "task_id": launched["task_id"], "queue_position": launched["queue_position"]})
    card.status, card.result = "done", {"runs": results}

    added = [r for r in results if "task_id" in r]
    lines = [f"n°{r['n']} → {r['task_id']} (position {r['queue_position']})" for r in added]
    lines += [f"n°{r['n']} refusé : {r['error']}" for r in results if "error" in r]
    session.note(f"{len(added)} run(s) ajouté(s) à la file sur {len(selected)} coché(s) : " + " ; ".join(lines))
