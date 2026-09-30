"""Les assets du bucket : avatars (liste et import) et catalogue de voix (liste et écoute)."""

from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.channels import bucket_key
from app.deps import BucketStorage
from app.storage import AVATAR_PREFIX, IMAGE_TYPES, VIDEO_TYPES, VOICE_KEY, avatars, slug, voices

router = APIRouter(prefix="/api/assets", tags=["assets"])

MAX_UPLOAD = 200 * 1024 * 1024
"""Une vidéo d'avatar de quelques secondes pèse bien moins ; au-delà, c'est une erreur."""


@router.get("/avatars")
def list_avatars(storage: BucketStorage) -> list[dict]:
    return avatars(storage)


@router.post("/avatars", status_code=201)
def upload_avatar(
    storage: BucketStorage,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()] = "",
) -> dict:
    """Importe une image ou une vidéo sous `avatars/`. Un nom déjà pris reçoit un suffixe."""
    suffix = PurePosixPath(file.filename or "").suffix.lower()
    kinds = IMAGE_TYPES | VIDEO_TYPES
    if suffix not in kinds:
        raise HTTPException(422, f"Format non pris en charge : {', '.join(sorted(kinds))}.")
    if file.size is not None and file.size > MAX_UPLOAD:
        raise HTTPException(413, f"Fichier trop lourd : {MAX_UPLOAD // (1024 * 1024)} Mo au plus.")
    stem = slug(name or PurePosixPath(file.filename or "").stem) or "avatar"
    key = storage.free_key(AVATAR_PREFIX, stem, suffix)
    storage.upload(file.file, key, kinds[suffix])
    return next(avatar for avatar in avatars(storage) if avatar["uri"] == storage.uri(key))


@router.get("/voices")
def list_voices(storage: BucketStorage) -> list[dict]:
    return voices(storage)


@router.get("/voices/info")
def voice_info(uri: str, storage: BucketStorage) -> dict:
    """La fiche d'une voix (description, texte lu, durée), rangée à côté du .wav."""
    key = bucket_key(uri)
    if not key or not VOICE_KEY.fullmatch(key):
        raise HTTPException(422, "Ce n'est pas une voix du catalogue.")
    sheet = storage.read_json(key.removesuffix(".wav") + ".json")
    return {field: sheet.get(field) for field in ("name", "description", "text", "duration_s")}
