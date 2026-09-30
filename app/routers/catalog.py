"""Tout ce que l'éditeur propose : styles, langues, fournisseurs, types de paramètres, aides."""

import json
from functools import cache
from pathlib import Path

from fastapi import APIRouter, Request

from app import task_config
from app.channels import ChannelAgent, ChannelModels
from app.params import PARAM_TYPES
from app.schema_docs import attribute_docs
from app.task_config import LANGUAGE_NAMES, PROVIDERS

router = APIRouter(prefix="/api", tags=["catalog"])

SKILLS_FILE = Path(__file__).resolve().parent.parent / "skills.json"

MODEL_SUGGESTIONS = {
    "foundry": ["claude-opus-4-7-1", "claude-haiku-4-5"],
    "sglang": ["MiniMaxAI/MiniMax-H3"],
}


@cache
def _help() -> dict[str, dict[str, str]]:
    """L'aide de chaque réglage, tirée des docstrings d'attribut du schéma du worker."""
    return attribute_docs(task_config)


@router.get("/catalog")
def catalog(request: Request) -> dict:
    return {
        "skills": json.loads(SKILLS_FILE.read_text("utf-8")) if SKILLS_FILE.exists() else [],
        "languages": LANGUAGE_NAMES,
        "providers": [
            {"id": key, "label": value["label"], "models": MODEL_SUGGESTIONS.get(key, [])}
            for key, value in PROVIDERS.items()
        ],
        "param_types": PARAM_TYPES,
        "defaults": {
            "agent_config": ChannelAgent().model_dump(mode="json"),
            "models": ChannelModels().model_dump(mode="json"),
        },
        "help": _help(),
        "storage": request.app.state.storage is not None,
    }
