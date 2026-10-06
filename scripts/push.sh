#!/usr/bin/env bash
# Construit et pousse l'image du service web vers le registre Scaleway, taguée au SHA du commit
# et `latest` (ce que `docker compose pull` récupère par défaut sur un autre poste).
#
# Connexion : `docker login rg.fr-par.scw.cloud -u nologin --password-stdin` une fois,
# ou SCW_SECRET_KEY dans l'environnement.
set -euo pipefail
cd "$(dirname "$0")/.."

REGISTRY=rg.fr-par.scw.cloud/mavg-container-registery # même valeur que dans docker-compose.yml

# Le tag dit exactement quel code tourne : on refuse de construire depuis des fichiers modifiés.
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Fichiers modifiés ou non suivis :" >&2
  git status --short >&2
  echo "Commite-les d'abord : sinon le tag ne décrirait pas le contenu de l'image." >&2
  exit 1
fi

# Les secrets du .env sont embarqués dans l'image : elle ne doit aller que dans le registre privé.
if [[ ! -f .env ]]; then
  echo "Pas de .env : l'image embarque ses secrets depuis ce fichier (modèle : .env.example)." >&2
  exit 1
fi

IMAGE="$REGISTRY/mavg-web:$(git rev-parse --short=12 HEAD)"
LATEST="$REGISTRY/mavg-web:latest"

if [[ -n "${SCW_SECRET_KEY:-}" ]]; then
  docker login rg.fr-par.scw.cloud -u nologin --password-stdin <<< "$SCW_SECRET_KEY" > /dev/null
fi

# Les secrets ne sont pas dans git : après en avoir changé un, le SHA est le même mais l'image
# doit être reconstruite. FORCE=1 la reconstruit et remplace le tag.
if [[ -z "${FORCE:-}" ]] && docker manifest inspect "$IMAGE" > /dev/null 2>&1; then
  echo "$IMAGE est déjà dans le registre : rien à faire (FORCE=1 pour la reconstruire, par exemple après un changement de secret)."
  exit 0
fi

# amd64 pour les serveurs (Serverless Containers, instances), arm64 pour les Mac Apple Silicon :
# `docker pull` choisit tout seul la bonne. Construit sans émulation (voir le Dockerfile).
# Le contenu d'un --secret n'entre pas dans la clé de cache de BuildKit : sans --no-cache-filter,
# l'étape `secrets` resservirait le .env d'un build précédent, même après un changement de secret.
docker buildx build --platform linux/amd64,linux/arm64 --secret id=env,src=.env \
  --no-cache-filter secrets -t "$IMAGE" -t "$LATEST" --push .
echo "Poussée : $IMAGE (et latest), pour linux/amd64 et linux/arm64"
