#!/usr/bin/env bash
# Recopie le schéma des tâches depuis le repo du worker.
#
#   scripts/sync_schema.sh                 depuis ../mavg/task_config.py
#   scripts/sync_schema.sh chemin/vers.py  depuis un autre emplacement
#
# Le service valide avec ce schéma avant d'insérer : s'il diverge du worker, une tâche
# acceptée ici peut être refusée là-bas. Le test `test_schema_copy_matches_the_worker`
# échoue tant que les deux copies diffèrent.
set -euo pipefail
cd "$(dirname "$0")/.."

SOURCE="${1:-../mavg/task_config.py}"
if cmp -s "$SOURCE" app/task_config.py; then
  echo "app/task_config.py est déjà à jour."
  exit 0
fi
cp "$SOURCE" app/task_config.py
echo "app/task_config.py mis à jour depuis $SOURCE. Relancer les tests : uv run pytest"
