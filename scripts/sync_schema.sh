#!/usr/bin/env bash
# Recopie depuis le repo du worker ce que l'interface doit partager avec lui.
#
#   scripts/sync_schema.sh                 depuis ../mavg
#   scripts/sync_schema.sh chemin/du/repo  depuis un autre emplacement
#
# 1. app/task_config.py : le schéma des tâches, le registre des fournisseurs, la version.
#    S'il diverge du worker, un run accepté ici peut être refusé là-bas : le test
#    `test_schema_copy_matches_the_worker` échoue tant que les deux copies diffèrent.
# 2. app/skills.json : les styles proposés dans l'éditeur de channel (skills/styles/*),
#    lus dans leur front matter. Le conteneur web n'a pas le dossier skills/ du worker.
set -euo pipefail
cd "$(dirname "$0")/.."

WORKER="${1:-../mavg}"

if cmp -s "$WORKER/task_config.py" app/task_config.py; then
  echo "app/task_config.py est déjà à jour."
else
  cp "$WORKER/task_config.py" app/task_config.py
  echo "app/task_config.py mis à jour depuis $WORKER."
fi

# Le venv du worker a pyyaml : les descriptions de skills sont des blocs YAML multilignes.
"$WORKER/.venv/bin/python" - "$WORKER/skills/styles" app/skills.json <<'PY'
import json, sys
from pathlib import Path
import yaml

styles_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
styles = []
for skill_md in sorted(styles_dir.glob("*/SKILL.md")):
    front = yaml.safe_load(skill_md.read_text("utf-8").split("---")[1]) or {}
    meta_path = skill_md.with_name("meta.yaml")
    meta = yaml.safe_load(meta_path.read_text("utf-8")) if meta_path.exists() else {}
    styles.append({
        "name": front["name"],
        "tag": meta.get("tag-en", ""),
        "summary": (meta.get("summary-en") or front.get("description", "")).strip(),
    })
out.write_text(json.dumps(styles, ensure_ascii=False, indent=2) + "\n", "utf-8")
print(f"{out} : {len(styles)} style(s).")
PY
echo "Relancer les tests : uv run pytest"
