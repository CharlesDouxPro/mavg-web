# MAVG Studio

L'interface web du worker vidéo [`mavg`](../mavg). On y enregistre des **channels** (des
configs de base : brief, avatar, voix, style, paramètres), on les édite, et on **lance des
runs** depuis eux en remplissant leurs paramètres. Chaque `${paramètre}` cité dans le brief
est remplacé par la valeur du run.

```
Channels ──édite──▶ Mongo.channels          (mis à jour en place, versionné)
    │ Lancer + paramètres
    ▼
rendu ${…} ──▶ Mongo.tasks (copie figée, pending) ──▶ worker mavg (FIFO) ──▶ bucket + e-mail
                         ▲                                 │
Runs · Galerie ◀── statut, étape, titre, vidéo ◀───────────┘
```

Un seul processus sert l'API (`/api`) et le front (`/`), sur une seule origine. Le navigateur
ne parle jamais à MongoDB ni au bucket : il n'y lit qu'au travers de liens signés.

## Les trois onglets

- **Channels** — la liste et l'éditeur. Général (nom, style, langue), Brief (prompt à
  `${…}` surlignés, aperçu en direct de ce que l'agent reçoit), Paramètres de run (type,
  défaut, requis ; renommer met à jour les citations), Avatar & voix (avatars du bucket,
  import par glisser-déposer, catalogue de voix à écouter), Publication (dossier, e-mail,
  mentions obligatoires), Modèles, Avancé. `Ctrl+S` enregistre.
- **Runs** — la file dans l'ordre où le worker la traite, et l'historique. Chaque run
  montre son étape en direct (planification → rendu → publication), sa vidéo, son texte
  de publication, son erreur. « Relancer… » rouvre le formulaire avec les mêmes valeurs.
- **Galerie** — toutes les vidéos publiées dans le bucket, lues au survol.

Un lien `#/runs/<task_id>` ouvre directement le détail d'un run.

## Démarrer en local

Prérequis : [uv](https://docs.astral.sh/uv/) et Node 22 ou plus.

```bash
cp .env.example .env          # Mongo, clés du bucket, et WEB_USER / WEB_PASSWORD (ou AUTH_DISABLED=1)
uv sync
(cd frontend && npm install)

uv run uvicorn app.main:create_app --factory --reload   # API sur :8000
(cd frontend && npm run dev)                           # front sur :5173, /api relayé vers :8000
```

**Avec la vraie base, un run lancé sera traité par le worker** (et consommera du GPU). Pour
essayer sans risque, une base locale jetable :

```bash
docker compose --profile local-db up -d mongo     # puis MONGO_CONNECTION_STRING=mongodb://localhost:27017
```

Les premiers channels se créent à partir des tâches déjà passées dans la file :

```bash
uv run python scripts/seed_channels.py --dry-run   # ce qui serait créé
uv run python scripts/seed_channels.py
```

## Ce que le serveur garantit

- **Pas de secret dans un channel.** Un channel choisit un fournisseur et un nom de modèle ;
  l'adresse et la clé viennent du registre `PROVIDERS` du worker, sous forme de référence
  `${FOUNDRY_API_KEY}` résolue sur la machine du worker. Le worker vérifie lui-même qu'une
  de ses clés ne part que vers l'adresse de son fournisseur.
- **`${…}` ne sert qu'aux paramètres**, et seulement dans `brief.prompt`, `brief.mood` et
  `publication.must_include`. Un paramètre non déclaré ou mal écrit est refusé à
  l'enregistrement ; une valeur de run qui contient `${` est refusée au lancement. Le
  remplacement se fait en une passe : une valeur n'est jamais relue.
- **Un run est un instantané.** Modifier un channel ne change pas les runs déjà lancés. Un
  enregistrement fait sur une version périmée est refusé (409), comme un lancement depuis
  un formulaire ouvert avant une modification du channel.
- **Avatar et voix viennent du bucket** (`s3://mavg-object-storage/…`) : une adresse
  extérieure serait téléchargée par la machine GPU. L'avatar est vérifié avant le lancement.
- **Chemins et binaires de la machine du worker** (`render.output_dir`, `subtitles.ffmpeg_bin`…)
  ne s'éditent pas : ils sont remis à leur valeur.
- **Accès HTTP Basic**, fermé par défaut : sans `WEB_USER` et `WEB_PASSWORD`, le service
  refuse de démarrer. `AUTH_DISABLED=1` est réservé à un poste de dev.

## Le schéma partagé avec le worker

`app/task_config.py` est une copie de `../mavg/task_config.py` (schéma des tâches, registre
des fournisseurs, `SCHEMA_VERSION`), et `app/skills.json` liste les styles du worker.
Après tout changement côté worker :

```bash
scripts/sync_schema.sh && uv run pytest
```

Le test `test_schema_copy_matches_the_worker` échoue tant que les deux copies divergent.
Chaque run porte `schema_version` : le worker prévient s'il ne correspond pas au sien.

## Tests

```bash
uv run pytest          # l'API contre mongomock et un bucket en mémoire
uv run ruff check .
(cd frontend && npm run build)
```

## Déployer (Scaleway Serverless Containers)

```bash
scripts/push.sh        # construit et pousse l'image, taguée au SHA du commit
```

Variables à fournir au conteneur : `MONGO_CONNECTION_STRING`, `MONGO_PLATFORM_DATABASE_NAME`,
`SCW_ACCESS_KEY`, `SCW_SECRET_KEY`, `WEB_USER`, `WEB_PASSWORD`. Jamais `AUTH_DISABLED`.
