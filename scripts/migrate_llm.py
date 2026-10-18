"""Fait passer les channels et la file d'attente de Foundry au LLM local (`sglang-llm`).

- Channels : un rôle (`master_mind`, `slm`) écrit sur Foundry est retiré du document, qui
  reprend alors le défaut (`ChannelModels`, Qwen sur SGLang). La version monte : un
  éditeur ouvert avant la migration reçoit un 409 au lieu de réécrire Foundry.
- Brouillons de l'assistant : même chose, le brouillon reprend le défaut.
- Tâches `pending` : le rôle est réécrit en entier (fournisseur, modèle, adresse, clé),
  sinon le worker la refuse (« fournisseur 'foundry' inconnu »). Les tâches terminées
  restent telles quelles : ce sont des instantanés.

À lancer quand plus aucun worker de l'ancienne version ne tourne : lui ne connaît pas
`sglang-llm` et refuserait les tâches migrées. Chaque valeur remplacée est affichée.

    uv run python scripts/migrate_llm.py --dry-run
    uv run python scripts/migrate_llm.py
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient
from pymongo.database import Database

from app.channels import ChannelModels
from app.settings import Settings
from app.task_config import PROVIDERS

OLD = "foundry"
NEW = "sglang-llm"
ROLES = ("master_mind", "slm")


def _on_old(prefix: str) -> dict:
    return {"$or": [{f"{prefix}.{role}.provider": OLD} for role in ROLES]}


def _old_roles(models: dict) -> list[str]:
    return [role for role in ROLES if (models.get(role) or {}).get("provider") == OLD]


def migrate(db: Database, settings: Settings, *, apply: bool) -> list[str]:
    """Ce qui change (ou changerait, sans `apply`), une ligne par rôle."""
    report: list[str] = []
    now = datetime.now(UTC)
    defaults = ChannelModels()

    channels = db[settings.channels_collection]
    for doc in channels.find(_on_old("agent_config.models")):
        roles = _old_roles(doc["agent_config"]["models"])
        report += [f"channel {doc['_id']} : {role} {doc['agent_config']['models'][role]['model_name']} -> défaut" for role in roles]
        if apply:
            channels.update_one(
                {"_id": doc["_id"], "version": doc["version"]},
                {
                    "$unset": {f"agent_config.models.{role}": "" for role in roles},
                    "$set": {"version": doc["version"] + 1, "updated_at": now},
                },
            )

    sessions = db[settings.assistant_collection]
    for doc in sessions.find(_on_old("draft.agent_config.models")):
        roles = _old_roles(doc["draft"]["agent_config"]["models"])
        report += [f"brouillon {doc['_id']} : {role} -> défaut" for role in roles]
        if apply:
            sessions.update_one({"_id": doc["_id"]}, {"$unset": {f"draft.agent_config.models.{role}": "" for role in roles}})

    tasks = db[settings.mongo_collection]
    for doc in tasks.find({"status": "pending", **_on_old("agent_config.models")}):
        updates = {}
        for role in _old_roles(doc["agent_config"]["models"]):
            new = {
                "provider": NEW,
                "model_name": getattr(defaults, role).model_name,
                "base_url": PROVIDERS[NEW]["base_url"],
                "token": PROVIDERS[NEW]["token"],
            }
            report.append(f"tâche {doc['task_id']} : {role} {doc['agent_config']['models'][role]['model_name']} -> {new['model_name']}")
            updates[f"agent_config.models.{role}"] = new
        if apply:
            tasks.update_one({"_id": doc["_id"], "status": "pending"}, {"$set": updates})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="afficher sans rien écrire")
    args = parser.parse_args()

    settings = Settings.from_env()
    if not settings.mongo_configured:
        raise SystemExit("MONGO_CONNECTION_STRING et MONGO_PLATFORM_DATABASE_NAME sont requis (.env).")
    db = MongoClient(settings.mongo_connection_string)[settings.mongo_database]
    for line in migrate(db, settings, apply=not args.dry_run):
        print(line)
    print("Rien n'a été écrit (--dry-run)." if args.dry_run else "Migration terminée.")


if __name__ == "__main__":
    main()
