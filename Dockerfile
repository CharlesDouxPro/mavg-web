# syntax=docker/dockerfile:1
# MAVG Studio : FastAPI sert l'API (/api) et le build React (/). Pas de GPU, pas de ffmpeg.
#
# Image multi-architecture : linux/amd64 (serveurs) et linux/arm64 (Mac Apple Silicon),
# construite sans émulation. Les étapes qui exécutent une commande tournent sur
# l'architecture du poste de build ($BUILDPLATFORM) ; l'étape finale ne fait que copier.

# 1. Le front, compilé en fichiers statiques : le résultat ne dépend pas de l'architecture.
FROM --platform=$BUILDPLATFORM node:24-alpine AS front
WORKDIR /front
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2. Les dépendances Python de l'architecture CIBLE, installées depuis le poste de build :
#    uv télécharge les wheels amd64 ou arm64 sans rien exécuter de la cible.
FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:0.11.22-python3.13-trixie-slim AS deps
ARG TARGETARCH
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    case "$TARGETARCH" in \
      amd64) platform=x86_64-unknown-linux-gnu ;; \
      arm64) platform=aarch64-unknown-linux-gnu ;; \
      *) echo "Architecture non prise en charge : $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && uv sync --frozen --no-dev --no-install-project --python-platform "$platform"

# 3. Les secrets (Mongo, bucket, accès) sont embarqués : l'image suffit à tout lancer, sans
#    fichier sur le poste. Elle ne doit donc vivre que dans le registre PRIVÉ. Fournis par
#    `scripts/push.sh` (--secret id=env,src=.env) ; une variable passée au lancement (-e) prime.
#    Le contenu d'un secret n'entre pas dans la clé de cache de BuildKit : ENV_HASH, l'empreinte
#    du .env, est dans le nom du fichier copié. Une étape reprise du cache porte donc forcément
#    ce .env-là (sans quoi le cache a déjà resservi l'ancien .env à l'image arm64).
FROM --platform=$BUILDPLATFORM node:24-alpine AS secrets
ARG ENV_HASH
RUN --mount=type=secret,id=env,required=true test -n "$ENV_HASH" && cp /run/secrets/env "/env-$ENV_HASH"

# 4. L'image servie : Python slim, sans uv ni Node. Même interpréteur que l'étape 2, au
#    même chemin : le venv recopié fonctionne tel quel.
FROM python:3.13-slim-trixie
WORKDIR /app
COPY --from=deps /app/.venv .venv
COPY app/ app/
# Le certificat de l'autorité de la base managée : `tlsCAFile=certs/mgdb-mavg.pem`
# dans la chaîne de connexion, relatif à /app.
COPY certs/ certs/
COPY --from=front /front/dist frontend/dist
ARG ENV_HASH
COPY --from=secrets --chown=10001:10001 --chmod=0400 /env-${ENV_HASH} /app/.env

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PORT=8080
# Un utilisateur sans droits, désigné par son numéro : pas de `useradd`, donc rien à exécuter.
USER 10001:10001
EXPOSE 8080
# PORT est fixé par la plateforme (Scaleway Serverless Containers : 8080 par défaut).
# L'image embarque le .env du poste de build (AUTH_DISABLED=1 pour un usage local). Sur une
# URL publique : -e AUTH_DISABLED=0 -e WEB_USER=… -e WEB_PASSWORD=…
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
