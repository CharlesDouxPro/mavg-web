"""La migration Foundry -> LLM local : ce qu'elle réécrit, et ce qu'elle laisse."""

import sys
from datetime import UTC, datetime
from pathlib import Path

import mongomock

from app.channels import from_document
from app.settings import Settings
from app.task_config import PROVIDERS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from migrate_llm import migrate

SETTINGS = Settings()
FOUNDRY = {"provider": "foundry", "model_name": "claude-opus-5-5"}
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def channel(channel_id: str, models: dict | None) -> dict:
    agent = {"brief": {"prompt": "x"}} | ({"models": models} if models else {})
    return {
        "_id": channel_id,
        "name": channel_id,
        "channel_config": {"channel_name": channel_id, "email": ""},
        "agent_config": agent,
        "version": 3,
        "created_at": NOW,
        "updated_at": NOW,
    }


def task(task_id: str, status: str) -> dict:
    model = {"base_url": "https://${FOUNDRY_RESOURCE}.services.ai.azure.com/anthropic/", "token": "${FOUNDRY_API_KEY}"}
    return {
        "task_id": task_id,
        "status": status,
        "agent_config": {
            "models": {
                "master_mind": {**FOUNDRY, **model},
                "video_generator": {"provider": "sglang", "model_name": "MiniMaxAI/MiniMax-H3"},
            }
        },
    }


def seeded():
    db = mongomock.MongoClient().db
    db.channels.insert_many([channel("old", {"master_mind": FOUNDRY}), channel("plain", None)])
    db.tasks.insert_many([task("waiting", "pending"), task("done-already", "done")])
    db.assistant_sessions.insert_one({"_id": "s1", "draft": {"agent_config": {"models": {"slm": FOUNDRY}}}})
    return db


def test_dry_run_reports_without_writing():
    db = seeded()
    report = migrate(db, SETTINGS, apply=False)
    assert report == [
        "channel old : master_mind claude-opus-5-5 -> défaut",
        "brouillon s1 : slm -> défaut",
        "tâche waiting : master_mind claude-opus-5-5 -> DavidAU/Qwen3.8-27B-TURBO-Fable-Cold-Fusion-735-882-Heretic-Uncensored-NM-DAU",
    ]
    assert db.channels.find_one({"_id": "old"})["agent_config"]["models"] == {"master_mind": FOUNDRY}


def test_channels_and_pending_tasks_move_to_the_local_llm():
    db = seeded()
    migrate(db, SETTINGS, apply=True)

    old = db.channels.find_one({"_id": "old"})
    assert old["version"] == 4  # un éditeur ouvert sur la v3 reçoit un 409
    assert from_document(old).agent_config.models.master_mind.provider == "sglang-llm"
    assert db.channels.find_one({"_id": "plain"})["version"] == 3

    waiting = db.tasks.find_one({"task_id": "waiting"})["agent_config"]["models"]
    assert waiting["master_mind"]["provider"] == "sglang-llm"
    assert waiting["master_mind"]["base_url"] == PROVIDERS["sglang-llm"]["base_url"]
    assert waiting["video_generator"]["provider"] == "sglang"
    # Une tâche terminée est un instantané : on n'y touche pas.
    assert db.tasks.find_one({"task_id": "done-already"})["agent_config"]["models"]["master_mind"] == {
        **FOUNDRY,
        "base_url": "https://${FOUNDRY_RESOURCE}.services.ai.azure.com/anthropic/",
        "token": "${FOUNDRY_API_KEY}",
    }

    assert db.assistant_sessions.find_one({"_id": "s1"})["draft"]["agent_config"]["models"] == {}
    assert migrate(db, SETTINGS, apply=False) == []
