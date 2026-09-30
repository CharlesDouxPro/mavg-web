"""Le schéma JSON du formulaire, avec l'aide de chaque champ.

Les docstrings d'attribut de `task_config.py` expliquent chaque réglage (pourquoi le
seed est fixe, ce que coûte `concurrency`…). Pydantic ne les met dans le schéma qu'avec
`use_attribute_docstrings`, que le fichier du worker n'active pas : on les lit dans le
source, pour garder la copie de `task_config.py` identique à l'original.
"""

import ast
import inspect
import re
from functools import cache
from types import ModuleType

from app import task_config, tasks


@cache
def form_schema() -> dict:
    schema = tasks.TaskCreate.model_json_schema()
    docs = {**attribute_docs(task_config), **attribute_docs(tasks)}
    for name, definition in [("TaskCreate", schema), *schema.get("$defs", {}).items()]:
        for field, doc in docs.get(name, {}).items():
            prop = definition.get("properties", {}).get(field)
            if prop is not None:
                prop.setdefault("description", doc)
    return schema


def attribute_docs(module: ModuleType) -> dict[str, dict[str, str]]:
    """{classe: {champ: docstring}} pour chaque `champ: type` suivi d'une chaîne."""
    docs: dict[str, dict[str, str]] = {}
    for node in ast.parse(inspect.getsource(module)).body:
        if not isinstance(node, ast.ClassDef):
            continue
        fields = {}
        for current, following in zip(node.body, node.body[1:]):
            if (
                isinstance(current, ast.AnnAssign)
                and isinstance(current.target, ast.Name)
                and isinstance(following, ast.Expr)
                and isinstance(following.value, ast.Constant)
                and isinstance(following.value.value, str)
            ):
                fields[current.target.id] = _paragraphs(following.value.value)
        docs[node.name] = fields
    return docs


def _paragraphs(docstring: str) -> str:
    """Les retours à la ligne du source sont de la mise en page : seuls les paragraphes restent."""
    return re.sub(r"(?<!\n)\n(?!\n)", " ", inspect.cleandoc(docstring))
