# syntax=docker/dockerfile:1
# MAVG Studio : FastAPI sert l'API (/api) et le build React (/). Pas de GPU, pas de ffmpeg.

# 1. Le front, compilé en fichiers statiques.
FROM node:24-alpine AS front
WORKDIR /front
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2. Les dépendances Python, dans un venv que l'étape finale recopie.
FROM ghcr.io/astral-sh/uv:0.11.22-python3.13-trixie-slim AS deps
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# 3. L'image servie : Python slim, sans uv ni Node. Même interpréteur que l'étape 2,
#    au même chemin : le venv recopié fonctionne tel quel.
FROM python:3.13-slim-trixie
WORKDIR /app
RUN useradd --system --uid 10001 --no-create-home web
COPY --from=deps /app/.venv .venv
COPY app/ app/
# Le certificat de l'autorité de la base managée : `tlsCAFile=certs/mgdb-mavg.pem`
# dans la chaîne de connexion, relatif à /app.
COPY certs/ certs/
COPY --from=front /front/dist frontend/dist
# Les secrets (Mongo, bucket, accès) sont embarqués : l'image suffit à tout lancer, sans
# fichier sur le poste. Elle ne doit donc vivre que dans le registre PRIVÉ. Fournis par
# `scripts/push.sh` (--secret id=env,src=.env) ; une variable passée au lancement (-e) prime.
RUN --mount=type=secret,id=env,required=true \
    install -o web -g web -m 0400 /run/secrets/env /app/.env

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PORT=8080
USER web
EXPOSE 8080
# PORT est fixé par la plateforme (Scaleway Serverless Containers : 8080 par défaut).
# L'image embarque le .env du poste de build (AUTH_DISABLED=1 pour un usage local). Sur une
# URL publique : -e AUTH_DISABLED=0 -e WEB_USER=… -e WEB_PASSWORD=…
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
