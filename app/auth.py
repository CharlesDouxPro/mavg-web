"""L'accès à l'interface : HTTP Basic, fermé par défaut.

Lancer un run dépense du GPU et des appels LLM, et l'interface signe des liens vers le
bucket privé : sans identifiants configurés, le service refuse de démarrer (sauf
`AUTH_DISABLED=1`, sur un poste de dev). Le navigateur affiche sa propre fenêtre de
connexion et renvoie les identifiants à chaque requête : le front n'a rien à gérer.
"""

import base64
import binascii
import hmac

from fastapi import Request
from fastapi.responses import PlainTextResponse

from app.settings import Settings

PUBLIC_PATHS = {"/api/health"}


def check_settings(settings: Settings) -> None:
    if not settings.auth_disabled and not (settings.auth_user and settings.auth_password):
        raise RuntimeError(
            "Accès non protégé : renseigner WEB_USER et WEB_PASSWORD "
            "(ou AUTH_DISABLED=1 sur un poste de dev)."
        )


def authorized(header: str, settings: Settings) -> bool:
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        user, _, password = base64.b64decode(encoded).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    # Comparaison à temps constant : la durée ne dit pas combien de caractères sont justes.
    return hmac.compare_digest(user.encode(), settings.auth_user.encode()) & hmac.compare_digest(
        password.encode(), settings.auth_password.encode()
    )


def middleware(settings: Settings):
    async def basic_auth(request: Request, call_next):
        if settings.auth_disabled or request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        if authorized(request.headers.get("authorization", ""), settings):
            return await call_next(request)
        return PlainTextResponse(
            "Identifiants requis.",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="MAVG Studio", charset="UTF-8"'},
        )

    return basic_auth
