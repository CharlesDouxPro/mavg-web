"""Les modèles de tâche : le point de départ du formulaire.

Un modèle est une tâche complète sans date ni statut, plus un `label` pour la liste.
Ils fixent aussi les variables `${VAR}` qu'une tâche a le droit de référencer : ajouter
une variable au worker, c'est l'ajouter dans un modèle.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.tasks import PLACEHOLDER, TaskCreate


@dataclass(frozen=True)
class Template:
    id: str
    label: str
    task: dict
    """La tâche validée, valeurs par défaut comprises : le formulaire montre tout."""


@dataclass(frozen=True)
class Catalog:
    templates: list[Template]
    env_refs: frozenset[str]


def load_catalog(directory: Path) -> Catalog:
    """Charge et valide les modèles. Un modèle invalide empêche le service de démarrer."""
    templates, env_refs = [], set()
    for path in sorted(directory.glob("*.json")):
        raw = path.read_text("utf-8")
        env_refs.update(PLACEHOLDER.findall(raw))
        data = json.loads(raw)
        label = data.pop("label", path.stem)
        try:
            task = TaskCreate.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"Modèle de tâche invalide : {path}\n{exc}") from exc
        templates.append(Template(path.stem, label, task.model_dump(mode="json")))
    if not templates:
        raise ValueError(f"Aucun modèle de tâche dans {directory}")
    return Catalog(templates, frozenset(env_refs))
