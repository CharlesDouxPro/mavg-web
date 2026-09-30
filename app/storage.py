"""Le bucket vu par l'interface : aperçus d'avatars, écoute des voix, vidéos publiées.

Le bucket est privé : le navigateur n'y lit qu'au travers de liens signés, valables une
heure, servis en lecture (`inline`) pour que `<video>` et `<audio>` les jouent. L'écriture
se limite à l'import d'avatars, sous `avatars/`.
"""

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import IO, Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.task_config import StorageConfig

AVATAR_PREFIX = "avatars/"
VOICE_PREFIX = "voices/"
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
VIDEO_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
MEDIA_TYPES = {**IMAGE_TYPES, **VIDEO_TYPES, ".wav": "audio/wav", ".mp3": "audio/mpeg"}
LINK_TTL_S = 3600
LIST_TTL_S = 300
VOICE_KEY = re.compile(r"voices/([a-z]{2})/(\w+)/([\w-]+)/([^/]+)\.wav")


def content_type(key: str) -> str | None:
    return MEDIA_TYPES.get(PurePosixPath(key).suffix.lower())


def slug(text: str) -> str:
    ascii_only = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")[:60]


@dataclass
class Listed:
    key: str
    size: int
    modified: float


class Storage:
    def __init__(self, access_key: str, secret_key: str, config: StorageConfig | None = None):
        config = config or StorageConfig()
        self.bucket = config.bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            region_name=config.region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4", connect_timeout=10, read_timeout=60),
        )
        self._cache: dict[str, tuple[float, list[Listed]]] = {}
        self._texts: dict[str, str] = {}

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def link(self, key: str, *, filename: str | None = None, expires_s: int = LINK_TTL_S) -> str:
        """Un lien signé : en lecture dans la page, ou en téléchargement avec `filename`."""
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        else:
            params["ResponseContentDisposition"] = "inline"
            if kind := content_type(key):
                params["ResponseContentType"] = kind
        return self.client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires_s)

    def list(self, prefix: str, shallow: bool = False) -> list[Listed]:
        """Les objets sous `prefix` (sans descendre dans les dossiers avec `shallow`).

        Mis en cache quelques minutes : un listing par page vue, pas par requête.
        """
        cache_key = f"{prefix}|{shallow}"
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < LIST_TTL_S:
            return cached[1]
        options: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix}
        if shallow:
            options["Delimiter"] = "/"
        pages = self.client.get_paginator("list_objects_v2").paginate(**options)
        items = [
            Listed(obj["Key"], obj["Size"], obj["LastModified"].timestamp())
            for page in pages
            for obj in page.get("Contents", [])
        ]
        self._cache[cache_key] = (time.monotonic(), items)
        return items

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    def read_text(self, key: str) -> str:
        """Un petit fichier texte du bucket. Gardé en mémoire : une publication ne change pas."""
        if key not in self._texts:
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            self._texts[key] = body.decode("utf-8", "replace")
        return self._texts[key]

    def read_json(self, key: str) -> dict:
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return json.loads(body)

    def upload(self, stream: IO[bytes], key: str, kind: str) -> None:
        self.client.upload_fileobj(stream, self.bucket, key, ExtraArgs={"ContentType": kind})
        self._cache.clear()

    def free_key(self, prefix: str, stem: str, suffix: str) -> str:
        """`prefix/stem.ext`, ou `stem-2.ext`… si le nom est pris : un import n'écrase rien."""
        taken = {item.key for item in self.list(prefix)}
        candidate, index = f"{prefix}{stem}{suffix}", 2
        while candidate in taken:
            candidate, index = f"{prefix}{stem}-{index}{suffix}", index + 1
        return candidate


def avatars(storage: Storage) -> list[dict]:
    """Les avatars : les images et vidéos de `avatars/`, et celles posées à la racine."""
    items = [
        item
        for item in storage.list(AVATAR_PREFIX) + storage.list("", shallow=True)
        if PurePosixPath(item.key).suffix.lower() in IMAGE_TYPES | VIDEO_TYPES
    ]
    unique = {item.key: item for item in items}.values()
    return [
        {
            "uri": storage.uri(item.key),
            "name": PurePosixPath(item.key).stem,
            "kind": "video" if PurePosixPath(item.key).suffix.lower() in VIDEO_TYPES else "image",
            "url": storage.link(item.key),
            "size": item.size,
        }
        for item in sorted(unique, key=lambda item: item.modified, reverse=True)
    ]


def voices(storage: Storage) -> list[dict]:
    """Le catalogue de voix : langue, sexe, âge et prénom se lisent dans la clé."""
    found = []
    for item in storage.list(VOICE_PREFIX):
        match = VOICE_KEY.fullmatch(item.key)
        if not match:
            continue
        language, sex, age, name = match.groups()
        found.append(
            {
                "uri": storage.uri(item.key),
                "name": name,
                "language": language,
                "sex": sex,
                "age_range": age,
                "url": storage.link(item.key),
            }
        )
    return sorted(found, key=lambda v: (v["language"], v["sex"], v["age_range"], v["name"]))
