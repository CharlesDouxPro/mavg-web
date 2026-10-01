"""Les paramètres de run : leur grammaire `${nom}`, leurs types, et la substitution.

Un paramètre est déclaré sur le channel (nom, type, défaut) et cité dans le brief par
`${nom}`. Au lancement, la valeur saisie remplace chaque citation, en une seule passe :
une valeur n'est jamais relue, même si elle contient elle-même `${…}`.

Un paramètre `image` est à part : sa valeur est une image du bucket, envoyée au moteur
avec chaque plan (`app/render.py`). Dans le brief, il s'écrit par son label, `<Subject 2>`.
"""

import math
import re
from pathlib import PurePosixPath
from typing import Any, Literal

from app.storage import IMAGE_TYPES, bucket_key

ParamType = Literal["string", "text", "url", "number", "boolean", "image"]
PARAM_TYPES: dict[str, str] = {
    "string": "Texte court",
    "text": "Texte long",
    "url": "Lien",
    "number": "Nombre",
    "boolean": "Oui / non",
    "image": "Image",
}

PARAM_NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
"""Minuscules, chiffres et `_`, en commençant par une lettre : `source_url`, `idee`."""

TOKEN = re.compile(r"\$\{([a-z][a-z0-9_]{0,39})\}")

URL = re.compile(r"https?://[^\s/?#]+(?:[/?#]\S*)?")
MAX_URL = 2048
MAX_STRING = 500
MAX_TEXT = 50_000
TRUE = {"true", "1", "oui", "yes", "on", "vrai"}
FALSE = {"false", "0", "non", "no", "off", "faux"}


def scan(text: str) -> tuple[list[str], list[str]]:
    """Les paramètres cités dans `text`, et les fragments `${…}` mal formés.

    `$5`, `$nom` ou un `$` isolé restent du texte : seul `${` ouvre une citation.
    """
    names: list[str] = []
    malformed: list[str] = []
    position = 0
    while (start := text.find("${", position)) != -1:
        end = text.find("}", start + 2)
        if end == -1:
            malformed.append(text[start : start + 24])
            break
        inner = text[start + 2 : end]
        if PARAM_NAME.fullmatch(inner):
            names.append(inner)
        else:
            malformed.append(text[start : end + 1])
        position = end + 1
    return names, malformed


def render(text: str, values: dict[str, str], keep_missing: bool = False) -> str:
    """Remplace chaque `${nom}` par sa valeur, en une passe (la valeur n'est pas relue).

    Un nom sans valeur devient une chaîne vide, ou reste `${nom}` avec `keep_missing`
    (l'aperçu montre ainsi ce qui manque).
    """
    return TOKEN.sub(
        lambda match: values.get(match[1], match[0] if keep_missing else ""), text
    )


def is_empty(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and raw.strip() == "")


def coerce(kind: str, raw: Any) -> Any:
    """La valeur saisie, typée. Lève `ValueError` avec un message pour l'utilisateur."""
    if kind == "boolean":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in TRUE:
            return True
        if text in FALSE:
            return False
        raise ValueError("Attendu : oui ou non.")
    if kind == "number":
        if isinstance(raw, bool):
            raise ValueError("Attendu : un nombre.")
        try:
            number = float(raw) if isinstance(raw, (int, float)) else float(
                str(raw).strip().replace(",", ".")
            )
        except ValueError:
            raise ValueError("Attendu : un nombre.") from None
        if not math.isfinite(number):
            raise ValueError("Attendu : un nombre fini.")
        return int(number) if number.is_integer() else number

    text = raw if isinstance(raw, str) else str(raw)
    if kind == "image":
        text = text.strip()
        key = bucket_key(text)
        if key is None or PurePosixPath(key).suffix.lower() not in IMAGE_TYPES:
            raise ValueError("Attendu : une image du bucket (PNG, JPEG ou WebP), à choisir ou importer.")
        return text
    if kind == "url":
        text = text.strip()
        if len(text) > MAX_URL or not URL.fullmatch(text):
            raise ValueError("Attendu : une adresse qui commence par http:// ou https://.")
        return text
    if kind == "string":
        text = text.strip()
        if "\n" in text:
            raise ValueError("Une seule ligne : choisir le type « Texte long » sinon.")
        if len(text) > MAX_STRING:
            raise ValueError(f"{MAX_STRING} caractères au plus : choisir « Texte long » sinon.")
        return text
    text = text.replace("\r\n", "\n").strip()
    if len(text) > MAX_TEXT:
        raise ValueError(f"{MAX_TEXT} caractères au plus.")
    return text


def as_text(value: Any) -> str:
    """La valeur telle qu'elle s'écrit dans le prompt."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
