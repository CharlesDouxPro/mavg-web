# mavg-web

Un formulaire web qui pousse des tâches dans la file MongoDB du worker [`mavg`](../mavg).
Une tâche envoyée arrive en `pending` dans la collection `tasks`. Le worker la prend
à son prochain passage, en commençant par la plus récente.

```
Navigateur ──▶ FastAPI ── /api/*  ──▶ MongoDB (collection tasks) ◀── worker mavg (main.py)
                   └───── /       ──▶ build React (frontend/dist)
```

Un seul processus sert l'API et le front, sur une seule origine, donc sans CORS. Le navigateur
ne parle jamais à MongoDB : la chaîne de connexion reste côté serveur.

## Démarrer en local

Prérequis : [uv](https://docs.astral.sh/uv/) et Node 22 ou plus.

```bash
cp .env.example .env          # renseigner MONGO_CONNECTION_STRING et MONGO_PLATFORM_DATABASE_NAME
uv sync
(cd frontend && npm install)

uv run uvicorn app.main:app --reload       # API sur :8000
(cd frontend && npm run dev)               # front sur :5173, /api relayé vers :8000
```

**Avec la vraie chaîne de connexion, une tâche poussée sera traitée par le worker.** Pour
faire des essais, utilisez une base locale jetable :

```bash
docker compose --profile local-db up -d mongo
# puis dans .env : MONGO_CONNECTION_STRING=mongodb://127.0.0.1:27017
```

Pour tout lancer comme en production (image Docker, front compilé, port 8080) :

```bash
docker compose up -d --build     # http://localhost:8080
```

## Le formulaire

- **Modèle de tâche** : pré-remplit tout le formulaire. Les modèles sont les fichiers
  `templates/*.json`, c'est-à-dire une tâche complète sans `created_at` ni `status`, plus un `label`.
- **Essentiel** : identifiant, chaîne, email du rapport, brief, style, langue, `params`
  (le sujet précis de la vidéo) et avatar.
- **Options avancées** : les modèles (`provider`, `model_name`, `base_url`, `token`) et
  les réglages LLM, rendu, plan, sous-titres, publication, scraper et stockage. Cette partie est
  générée à partir du schéma : un champ ajouté à `task_config.py` y apparaît sans modifier le front,
  et sa docstring sert de texte d'aide.
- **Vérifier** affiche le document qui serait inséré, sans l'insérer (l'équivalent de
  `push_task.py --dry-run`). **Pousser en pending** l'insère.
- **File de tâches** : les 20 dernières tâches et leur statut.

### Ce que le serveur refuse, même quand le schéma l'accepte

| Règle | Pourquoi |
|---|---|
| `task_id` limité à `[A-Za-z0-9_-]`, 64 caractères au plus | Le worker en fait un dossier (`runs/<task_id>/`). |
| Secrets (`token`, `access_key`, `secret_key`) uniquement sous la forme `${VAR}` | La valeur se résout chez le worker et ne passe jamais par la base. |
| Seules les variables `${VAR}` présentes dans les modèles sont admises | Le worker résout n'importe quelle `${VAR}`, n'importe où dans la tâche : `${MONGO_CONNECTION_STRING}` dans un prompt ferait fuiter ce secret. |
| `render.output_dir`, `render.final_name`, `storage.cache_dir` et `subtitles.ffmpeg_bin` verrouillés | Ce sont des chemins et un binaire de la machine du worker, pas des réglages de la vidéo. |
| Email du rapport obligatoire | C'est lui qui reçoit le rapport de fin de vidéo. |
| Pas deux tâches avec le même `task_id` | Le worker met à jour le statut par `task_id`. |

Pour autoriser une nouvelle variable d'environnement, ajoutez-la dans un modèle.

### Le document inséré

Le serveur ajoute `created_at` (UTC), `status: "pending"`, et suffixe l'identifiant par
`_MMJJ_HHMMSS`, comme `push_task.py`. Le document contient la configuration complète,
valeurs par défaut comprises : le worker lit exactement ce que le formulaire a affiché.

## Le schéma partagé avec le worker

`app/task_config.py` est une **copie à l'identique** de `mavg/task_config.py`. Quand le
schéma change dans `mavg` :

```bash
scripts/sync_schema.sh      # recopie depuis ../mavg/task_config.py
uv run pytest
```

Le test `test_schema_copy_matches_the_worker` échoue tant que les deux copies diffèrent,
si le repo `mavg` est à côté.

## Tests

```bash
uv run pytest               # l'API contre un Mongo en mémoire (mongomock)
uv run ruff check .
(cd frontend && npm run typecheck)
```

## Configuration

| Variable | Défaut | |
|---|---|---|
| `MONGO_CONNECTION_STRING` | | Même chaîne que le worker. Pour la base managée Scaleway, garder `tlsCAFile=certs/mgdb-mavg.pem` (chemin relatif à la racine du repo, ou à `/app` dans l'image). |
| `MONGO_PLATFORM_DATABASE_NAME` | | |
| `MONGO_COLLECTION` | `tasks` | La collection que le worker consomme. |
| `PORT` | `8080` | Dans l'image uniquement. |

## Image

```bash
scripts/push.sh     # construit et pousse rg.fr-par.scw.cloud/mavg-container-registery/mavg-web:<sha>
```

L'image contient Python slim, les dépendances, l'API et le front compilé. Elle n'inclut ni Node
ni uv, et tourne sous un utilisateur non-root. Aucun secret n'y est copié : ils passent par
l'environnement.

## Avant une mise en ligne

Ce service n'a **pas encore d'authentification**. Toute personne qui atteint l'URL peut
pousser des tâches, donc consommer du GPU et des tokens, et faire envoyer des emails. Une
tâche peut aussi viser une `base_url` arbitraire avec `${FOUNDRY_API_KEY}` comme token : le
worker y enverrait la clé. Ne l'exposez pas sans login, ou au minimum sans une barrière d'accès.
