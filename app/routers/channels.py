"""Les channels : CRUD versionné, aperçu du prompt rendu, lancement d'un run."""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.channels import (
    Channel,
    ChannelIn,
    ChannelUpdate,
    bucket_key,
    from_document,
    normalized,
    to_document,
    validate_channel,
)
from app.deps import Channels, MaybeStorage, Tasks
from app.issues import issue, raise_if
from app.render import build_document, preview, resolve_values

log = logging.getLogger("mavg-web")
router = APIRouter(prefix="/api", tags=["channels"])


class RenderRequest(BaseModel):
    channel: ChannelIn
    values: dict[str, Any] = Field(default_factory=dict)


class LaunchRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    channel_version: int | None = None
    """La version affichée dans le formulaire : si le channel a changé depuis, 409."""


def _now() -> datetime:
    return datetime.now(UTC)


def _load(channels: Channels, channel_id: str) -> Channel:
    document = channels.find_one({"_id": channel_id})
    if document is None:
        raise HTTPException(404, f"Channel {channel_id} introuvable.")
    return from_document(document)


def _checked(channel: ChannelIn) -> tuple[ChannelIn, list[dict]]:
    channel = normalized(channel)
    errors, warnings = validate_channel(channel)
    raise_if(errors)
    return channel, warnings


def _avatar_preview(channel: Channel, storage: MaybeStorage) -> dict | None:
    key = bucket_key(channel.agent_config.avatar.avatar_url)
    if not key:
        return None
    return {
        "uri": channel.agent_config.avatar.avatar_url,
        "url": storage.link(key) if storage else None,
        "kind": "video" if key.lower().endswith((".mp4", ".mov", ".webm")) else "image",
    }


@router.get("/channels")
def list_channels(channels: Channels, tasks: Tasks, storage: MaybeStorage) -> list[dict]:
    loaded = [from_document(document) for document in channels.find().sort("name", 1)]
    stats = {
        row["_id"]: row
        for row in tasks.aggregate(
            [
                {"$match": {"channel_id": {"$in": [channel.id for channel in loaded]}}},
                {"$sort": {"created_at": -1}},
                {
                    "$group": {
                        "_id": "$channel_id",
                        "runs": {"$sum": 1},
                        "task_id": {"$first": "$task_id"},
                        "status": {"$first": "$status"},
                        "created_at": {"$first": "$created_at"},
                    }
                },
            ]
        )
    }
    return [
        {
            "id": channel.id,
            "name": channel.name,
            "description": channel.description,
            "channel_name": channel.channel_config.channel_name,
            "language": channel.agent_config.language,
            "skill": channel.agent_config.skill,
            "parameters": [parameter.name for parameter in channel.parameters],
            "avatar": _avatar_preview(channel, storage),
            "version": channel.version,
            "updated_at": channel.updated_at,
            "runs": stats.get(channel.id, {}).get("runs", 0),
            "last_run": (
                {key: stats[channel.id][key] for key in ("task_id", "status", "created_at")}
                if channel.id in stats
                else None
            ),
        }
        for channel in loaded
    ]


@router.get("/channels/{channel_id}")
def get_channel(channel_id: str, channels: Channels) -> dict:
    channel = _load(channels, channel_id)
    _, warnings = validate_channel(channel)
    return {"channel": channel, "warnings": warnings}


@router.post("/channels", status_code=201)
def create_channel(body: ChannelIn, channels: Channels) -> dict:
    channel, warnings = _checked(body)
    now = _now()
    try:
        channels.insert_one(to_document(channel, version=1, created_at=now, updated_at=now))
    except DuplicateKeyError:
        raise HTTPException(409, f"Un channel {channel.id} existe déjà : choisis un autre identifiant.") from None
    log.info("Channel créé : %s", channel.id)
    return {"channel": _load(channels, channel.id), "warnings": warnings}


@router.put("/channels/{channel_id}")
def update_channel(channel_id: str, body: ChannelUpdate, channels: Channels) -> dict:
    if body.id != channel_id:
        raise_if([issue(("id",), "L'identifiant d'un channel ne change pas : duplique-le plutôt.", body.id)])
    channel, warnings = _checked(ChannelIn.model_validate(body.model_dump(exclude={"version", "created_at", "updated_at"})))
    fields = to_document(channel, version=body.version + 1, created_at=_now(), updated_at=_now())
    for key in ("_id", "created_at"):
        fields.pop(key)
    # Verrou optimiste : la mise à jour n'a lieu que si personne n'a enregistré entre-temps.
    updated = channels.find_one_and_update(
        {"_id": channel_id, "version": body.version},
        {"$set": fields},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        current = _load(channels, channel_id)
        raise HTTPException(
            409,
            f"Ce channel a été modifié ailleurs (version {current.version}, tu éditais la "
            f"{body.version}). Recharge-le avant d'enregistrer.",
        )
    return {"channel": from_document(updated), "warnings": warnings}


@router.delete("/channels/{channel_id}", status_code=204)
def delete_channel(channel_id: str, channels: Channels, version: int = Query()) -> Response:
    """Les runs déjà lancés restent : ils portent chacun leur copie de la config."""
    if channels.delete_one({"_id": channel_id, "version": version}).deleted_count == 0:
        current = _load(channels, channel_id)
        raise HTTPException(409, f"Ce channel a changé depuis (version {current.version}) : recharge-le.")
    return Response(status_code=204)


@router.post("/render")
def render_preview(body: RenderRequest) -> dict:
    """Le prompt tel que l'agent le recevra. Marche aussi sur un brouillon non enregistré."""
    return preview(body.channel, body.values)


def queue_position(tasks: Tasks, created_at: datetime) -> int:
    return tasks.count_documents({"status": "pending", "created_at": {"$lte": created_at}})


@router.post("/channels/{channel_id}/runs", status_code=201)
def launch_run(channel_id: str, body: LaunchRequest, channels: Channels, tasks: Tasks, storage: MaybeStorage) -> dict:
    channel = _load(channels, channel_id)
    if body.channel_version is not None and body.channel_version != channel.version:
        raise HTTPException(
            409,
            f"Le channel a été modifié depuis l'ouverture du formulaire (version {channel.version}). "
            "Recharge-le pour lancer la bonne config.",
        )
    errors, _ = validate_channel(channel)
    avatar = channel.agent_config.avatar
    if not avatar.avatar_url:
        errors.append(issue(("channel", "agent_config", "avatar", "avatar_url"), "Ce channel n'a pas d'avatar : choisis-en un dans l'éditeur.", ""))
    values, value_issues = resolve_values(channel, body.values)
    if storage is not None:
        # L'avatar fourni par un paramètre (`${personnage}`) se vérifie avec les autres images du run.
        assets = [(("channel", "agent_config", "avatar", field), getattr(avatar, field)) for field in ("avatar_url", "voice_url")]
        assets += [(("values", p.name), values[p.name]) for p in channel.parameters if p.type == "image" and p.name in values]
        for loc, uri in assets:
            key = bucket_key(uri)
            if key and not storage.exists(key):
                errors.append(issue(loc, f"{uri} est introuvable dans le bucket.", uri))
    raise_if(errors + value_issues)

    for _ in range(3):
        document = build_document(channel, values, _now())
        try:
            tasks.insert_one(document)
            break
        except DuplicateKeyError:
            continue  # suffixe aléatoire déjà pris : on retire
    else:
        raise HTTPException(409, "Impossible d'attribuer un identifiant de run : réessaie.")
    log.info("Run lancé : %s", document["task_id"])
    return {
        "task_id": document["task_id"],
        "status": "pending",
        "queue_position": queue_position(tasks, document["created_at"]),
    }
