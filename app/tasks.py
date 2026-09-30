"""Ce qu'on pousse en base, et ce qu'on refuse d'y pousser.

Le schéma est celui du worker (`task_config.py`, recopié du repo `mavg`). Ce module
ajoute les règles propres à un formulaire : ce qu'un opérateur ne doit pas pouvoir
écrire dans une tâche, même quand le schéma l'accepte.
"""

import re
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.task_config import (
    AgentConfig,
    ChannelConfig,
    RenderSettings,
    StorageConfig,
    SubtitleSettings,
    TaskConfig,
)

Loc = tuple[str | int, ...]

TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


class TaskCreate(BaseModel):
    """Une tâche telle que le formulaire l'envoie : sans date ni statut, que le serveur fixe."""

    task_id: str = Field(json_schema_extra={"pattern": TASK_ID.pattern})
    """Le worker en fait un nom de dossier (`runs/<task_id>/`) : ni `/`, ni `..`."""
    channel_config: ChannelConfig
    agent_config: AgentConfig

    @field_validator("task_id")
    @classmethod
    def _folder_name(cls, value: str) -> str:
        if not TASK_ID.fullmatch(value):
            raise ValueError(
                "1 à 64 caractères : lettres, chiffres, _ et -, sans commencer par _ ou -."
            )
        return value


PLACEHOLDER = re.compile(r"\$\{(\w+)\}")
"""Une référence à une variable d'environnement du worker, résolue au chargement."""

SECRET_FIELDS = frozenset({"token", "access_key", "secret_key"})
"""Champs qui portent un secret : seule une référence `${VAR}` y est admise. La valeur se
résout chez le worker, elle ne passe jamais par la base."""

LOCKED_FIELDS: dict[Loc, Any] = {
    ("agent_config", "render", "output_dir"): RenderSettings().output_dir,
    ("agent_config", "render", "final_name"): RenderSettings().final_name,
    ("agent_config", "storage", "cache_dir"): StorageConfig().cache_dir,
    ("agent_config", "subtitles", "ffmpeg_bin"): SubtitleSettings().ffmpeg_bin,
}
"""Réglages de la machine du worker, pas de la vidéo. Ce sont des chemins et un binaire
que le worker exécute : les ouvrir au formulaire laisserait écrire ou lancer n'importe
quoi sur la machine."""

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def check(task: TaskCreate, env_refs: frozenset[str]) -> list[dict]:
    """Les règles du formulaire, au-delà du schéma. Vide : la tâche peut partir.

    Les erreurs ont la forme de celles de FastAPI, pour que le front les affiche de la
    même façon, sous le champ concerné.
    """
    data = task.model_dump(mode="json")
    issues = []

    email = task.channel_config.email
    if not EMAIL.match(email):
        issues.append(
            _issue(
                ("channel_config", "email"),
                "Adresse email invalide : c'est elle qui reçoit le rapport de la vidéo.",
                email,
            )
        )

    for loc, value in _strings(data):
        unknown = sorted(set(PLACEHOLDER.findall(value)) - env_refs)
        if unknown:
            issues.append(
                _issue(
                    loc,
                    f"Variable inconnue : ${{{unknown[0]}}}. Le worker la remplacerait par sa "
                    f"valeur. Variables admises : {', '.join(sorted(env_refs))}.",
                    value,
                )
            )
        elif loc[-1] in SECRET_FIELDS and not re.fullmatch(r"(\$\{\w+\})?", value):
            issues.append(
                _issue(
                    loc,
                    "Un secret s'écrit ${NOM_DE_VARIABLE}, jamais en clair : la valeur se "
                    "résout chez le worker.",
                    "***",
                )
            )

    for loc, expected in LOCKED_FIELDS.items():
        value = _get(data, loc)
        if value != expected:
            issues.append(
                _issue(
                    loc,
                    f"Réglage de la machine du worker, non modifiable depuis le formulaire "
                    f"(valeur attendue : {expected!r}).",
                    value,
                )
            )
    return issues


def build_document(task: TaskCreate, now: datetime) -> dict:
    """Le document inséré : daté, en `pending`, l'identifiant suffixé.

    Le suffixe horodaté, au format de `push_task.py`, empêche une tâche repoussée
    d'écraser les sorties de la précédente. Le document est la config complète, valeurs
    par défaut comprises : le worker lit exactement ce que le formulaire a montré.
    """
    config = TaskConfig(
        created_at=now,
        task_id=f"{task.task_id}_{now:%m%d_%H%M%S}",
        status="pending",
        channel_config=task.channel_config,
        agent_config=task.agent_config,
    )
    return config.model_dump()


def _issue(loc: Loc, msg: str, value: Any) -> dict:
    return {"type": "form_rule", "loc": ("body", *loc), "msg": msg, "input": value}


def _strings(value: Any, loc: Loc = ()) -> Iterator[tuple[Loc, str]]:
    if isinstance(value, str):
        yield loc, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, (*loc, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, (*loc, index))


def _get(data: Any, loc: Loc) -> Any:
    for key in loc:
        data = data[key]
    return data
