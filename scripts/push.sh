#!/usr/bin/env bash
# Construit et pousse l'image du service web vers le registre Scaleway, taguée au SHA du commit.
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

IMAGE="$REGISTRY/mavg-web:$(git rev-parse --short=12 HEAD)"

if [[ -n "${SCW_SECRET_KEY:-}" ]]; then
  docker login rg.fr-par.scw.cloud -u nologin --password-stdin <<< "$SCW_SECRET_KEY" > /dev/null
fi

if docker manifest inspect "$IMAGE" > /dev/null 2>&1; then
  echo "$IMAGE est déjà dans le registre : rien à faire."
  exit 0
fi

# Serverless Containers tourne en amd64 : on le fixe pour qu'un build depuis un Mac ARM marche aussi.
docker build --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"
echo "Poussée : $IMAGE"
