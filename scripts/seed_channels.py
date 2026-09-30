"""Crée les premiers channels à partir des tâches déjà passées dans la file.

Chaque famille de tâches (`news_gyokeres_live_0917_020312` → `news_gyokeres_live`) donne
un channel, bâti sur sa tâche la plus récente : son brief, son avatar, son e-mail et ses
réglages. Ses `params` deviennent des paramètres de run, avec la valeur de la tâche pour
défaut. Le libellé vient du template du même nom (`templates/*.json`) s'il existe.

Passe par la même validation que l'API. Un channel qui existe déjà n'est pas touché.

    uv run python scripts/seed_channels.py --dry-run
    uv run python scripts/seed_channels.py
"""

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient

from app.channels import ChannelIn, normalized, to_document, validate_channel
from app.settings import Settings

LEGACY_SUFFIX = re.compile(r"_\d{4}_\d{6}$")
AGENT_FIELDS = ("skill", "language", "brief", "avatar", "llm", "render", "plan", "publication", "subtitles")
ROLES = ("master_mind", "slm", "video_generator")


def labels() -> dict[str, str]:
    found = {}
    for path in (ROOT / "templates").glob("*.json"):
        data = json.loads(path.read_text("utf-8"))
        found[data.get("task_id", path.stem)] = data.get("label", path.stem)
    return found


def parameter(name: str, value) -> dict:
    text = str(value)
    if name.endswith("_url") or text.startswith(("http://", "https://")):
        kind = "url"
    elif name == "source_text" or len(text) > 200 or "\n" in text:
        kind = "text"
    else:
        kind = "string"
    return {"name": name, "type": kind, "default": text}


def to_channel(task: dict, label: str | None) -> ChannelIn:
    base = LEGACY_SUFFIX.sub("", task["task_id"])
    agent = task["agent_config"]
    config = {field: agent[field] for field in AGENT_FIELDS if field in agent}
    config["models"] = {
        role: {"provider": agent["models"][role]["provider"], "model_name": agent["models"][role]["model_name"]}
        for role in ROLES
    }
    return ChannelIn.model_validate(
        {
            "id": base.replace("_", "-")[:40].strip("-"),
            "name": label or base.replace("_", " ").capitalize(),
            "description": f"Importé depuis la tâche {task['task_id']}.",
            "channel_config": task["channel_config"],
            "parameters": [parameter(name, value) for name, value in (agent.get("params") or {}).items()],
            "agent_config": config,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="afficher sans rien écrire")
    args = parser.parse_args()

    settings = Settings.from_env()
    if not settings.mongo_configured:
        raise SystemExit("MONGO_CONNECTION_STRING et MONGO_PLATFORM_DATABASE_NAME sont requis (.env).")
    database = MongoClient(settings.mongo_connection_string, tz_aware=True)[settings.mongo_database]
    tasks, channels = database[settings.mongo_collection], database[settings.channels_collection]

    latest: dict[str, dict] = {}
    for task in tasks.find({"channel_id": {"$exists": False}}).sort("created_at", 1):
        latest[LEGACY_SUFFIX.sub("", task["task_id"])] = task
    known = labels()

    now = datetime.now(UTC)
    for base, task in sorted(latest.items()):
        try:
            channel = normalized(to_channel(task, known.get(base)))
        except (KeyError, ValueError) as exc:
            print(f"✗ {base} : tâche illisible ({exc})")
            continue
        errors, warnings = validate_channel(channel)
        status = "existe déjà" if channels.count_documents({"_id": channel.id}, limit=1) else "nouveau"
        print(f"{'✗' if errors else '✓'} {channel.id:24s} « {channel.name} » — {len(channel.parameters)} paramètre(s), {status}")
        for problem in errors + warnings:
            print(f"    {'erreur' if problem in errors else 'note  '} {'.'.join(map(str, problem['loc'][1:]))} : {problem['msg']}")
        if errors or status != "nouveau" or args.dry_run:
            continue
        channels.insert_one(to_document(channel, version=1, created_at=now, updated_at=now))
    if args.dry_run:
        print("\n[dry-run] rien n'a été écrit.")


if __name__ == "__main__":
    main()
