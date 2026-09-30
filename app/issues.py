"""Les erreurs de validation au format de FastAPI, pour que le front les affiche sous le champ."""

from collections.abc import Iterator
from typing import Any

from fastapi.exceptions import RequestValidationError

Loc = tuple[str | int, ...]


def issue(loc: Loc, msg: str, value: Any = None) -> dict:
    return {"type": "form_rule", "loc": ("body", *loc), "msg": msg, "input": value}


def raise_if(issues: list[dict]) -> None:
    if issues:
        raise RequestValidationError(issues)


def strings(value: Any, loc: Loc = ()) -> Iterator[tuple[Loc, str]]:
    """Chaque chaîne d'un document, avec son chemin."""
    if isinstance(value, str):
        yield loc, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from strings(item, (*loc, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from strings(item, (*loc, index))
