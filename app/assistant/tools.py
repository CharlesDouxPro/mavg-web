"""Les outils de l'assistant : lire le Studio, construire le brouillon, poser des cartes.

Aucun outil n'écrit dans les channels, la file ou le bucket. Pour agir, l'agent pose une
carte, et c'est le clic de l'utilisateur qui exécute (`app/assistant/actions.py`), sur la
charge rangée dans la carte, jamais sur le texte du modèle.

Comme ceux du réalisateur (`mavg/agents/video_planner.py`), un outil ne lève jamais : il
renvoie au modèle, en clair, ce qui ne va pas, pour qu'il corrige.
"""

import functools
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from langchain_core.tools import InjectedToolCallId, tool
from pydantic import BaseModel, ValidationError
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.channels import (
    Channel,
    ChannelIn,
    ChannelParameter,
    from_document,
    normalized,
    validate_channel,
)
from app.render import preview, resolve_values
from app.routers.catalog import SKILLS_FILE
from app.storage import IMAGE_TYPES, VIDEO_TYPES, Storage, avatars, bucket_key, references, voices
from app.task_config import LANGUAGE_NAMES, ChannelConfig

log = logging.getLogger("mavg-web")

ENGINE_SHOT_SECONDS = (5, 15)
"""Ce que MiniMax-H3 accepte par clip (`MIN_SECONDS`, `MAX_SECONDS` de `mavg/providers/minimax_h3.py`)."""
MAX_CANDIDATES = 20
MAX_APPEARANCE_WORDS = 60
LISTED = 40
"""Au-delà, une liste d'images ou de voix noie le modèle sans l'aider."""

_sheets: dict[str, dict] = {}
"""Les fiches des voix, lues une fois : une voix du catalogue ne change pas."""

STUDIO_ERRORS = (HTTPException, RequestValidationError, ValidationError, ValueError, PyMongoError)
"""Ce que lèvent les routes et les modèles du Studio quand une demande est refusée."""


@dataclass
class Studio:
    """Ce que les outils et les cartes lisent et écrivent : les collections et le bucket."""

    channels: Collection
    tasks: Collection
    storage: Storage | None


class RunCandidate(BaseModel):
    pitch: str
    """L'idée en une ligne, telle que l'utilisateur la lira dans la carte."""
    values: dict[str, str]
    """La valeur de chaque paramètre du channel, par son nom."""


def explain(exc: Exception) -> str:
    """Une erreur des routes du Studio, en clair : celles-ci lèvent sous plusieurs formes."""
    if isinstance(exc, RequestValidationError):
        lines = []
        for error in exc.errors():
            loc = [str(part) for part in error.get("loc", ()) if part != "body"]
            lines.append(f"- {'.'.join(loc) or 'channel'} : {error.get('msg', 'valeur invalide')}")
        return "\n".join(lines)
    if isinstance(exc, HTTPException):
        return exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False)
    if isinstance(exc, ValidationError):
        return "\n".join(
            f"- {'.'.join(map(str, error['loc']))} : {error['msg']}" for error in exc.errors()
        )
    if isinstance(exc, PyMongoError):
        return "MongoDB injoignable pour l'instant : réessaie dans un moment."
    return str(exc) or exc.__class__.__name__


def blank_channel() -> ChannelIn:
    return ChannelIn(id="", name="", channel_config=ChannelConfig(channel_name="", email=""))


def _merge(base: dict, changes: dict) -> dict:
    merged = dict(base)
    for key, value in changes.items():
        merged[key] = _merge(merged[key], value) if isinstance(value, dict) and isinstance(merged.get(key), dict) else value
    return merged


def as_draft(channel: Channel) -> ChannelIn:
    return ChannelIn.model_validate(channel.model_dump(exclude={"version", "created_at", "updated_at"}))


def load_channel(studio: Studio, channel_id: str) -> Channel | None:
    document = studio.channels.find_one({"_id": channel_id})
    return from_document(document) if document else None


def voice_catalog(storage: Storage | None) -> dict[str, dict]:
    return {voice["uri"]: voice for voice in voices(storage)} if storage else {}


def voice_sheet(storage: Storage, uri: str) -> dict:
    if uri not in _sheets:
        key = bucket_key(uri) or ""
        try:
            _sheets[uri] = storage.read_json(key.removesuffix(".wav") + ".json")
        except (BotoCoreError, ClientError, KeyError, ValueError):  # une fiche illisible ne prive pas de la voix
            return {}
    return _sheets[uri]


def readiness(draft: ChannelIn) -> tuple[list[str], list[str]]:
    """(ce qui bloque l'enregistrement, ce qu'il vaut mieux régler) pour un brouillon.

    En plus des règles de l'éditeur (`validate_channel`), celles que le réalisateur impose
    à une vidéo réussie : une langue, et une apparence dès qu'il y a un avatar.
    """
    errors, warnings = validate_channel(normalized(draft))
    blocking = [_issue_text(item) for item in errors]
    advice = [_issue_text(item) for item in warnings]
    agent = draft.agent_config
    if not agent.language:
        blocking.append("agent_config.language : choisis la langue, sinon rien ne vérifie la langue des répliques.")
    if agent.avatar.avatar_url and not agent.avatar.appearance.strip():
        blocking.append("agent_config.avatar.appearance : décris l'avatar en anglais (set_avatar), c'est le verrou d'identité de chaque plan.")
        advice = [line for line in advice if not line.startswith("agent_config.avatar.appearance")]
    if not agent.avatar.voice_url:
        advice.append("agent_config.avatar.voice_url : sans voix, le modèle en invente une à chaque plan.")
    elif agent.language and f"/voices/{agent.language}/" not in agent.avatar.voice_url:
        advice.append("agent_config.avatar.voice_url : la voix n'est pas dans la langue du channel, l'accent suivra la voix.")
    return blocking, advice


def _issue_text(item: dict) -> str:
    loc = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
    return f"{loc} : {item.get('msg', '')}"


def describe(draft: ChannelIn, base_version: int | None) -> str:
    """Le brouillon en clair, pour l'agent."""
    agent = draft.agent_config
    plan = agent.plan
    state = f"version {base_version} enregistrée" if base_version is not None else "pas encore enregistré"
    silent = f"{plan.max_silent_shots} au plus" if plan.max_silent_shots else "aucun, l'avatar parle dans chaque plan"
    parameters = [
        f"{p.name} ({p.type}{', requis' if p.required else ''}{f', défaut « {p.default} »' if p.default else ''})"
        + (f" : {p.description}" if p.description else "")
        for p in draft.parameters
    ]
    lines = [
        f"Channel « {draft.id or '(sans identifiant)'} » — {draft.name or '(sans nom)'} ({state})",
        f"Description : {draft.description or '—'}",
        f"Langue : {agent.language or '—'} · style : {agent.skill or 'libre'}",
        f"Publication : dossier « {draft.channel_config.channel_name or '—'} », e-mail {draft.channel_config.email or '—'}",
        f"Brief : {agent.brief.prompt or '—'}",
        f"Mood : {agent.brief.mood or '—'}",
        f"Paramètres de run : {'; '.join(parameters) or 'aucun'}",
        f"Mentions obligatoires : {', '.join(agent.publication.must_include) or 'aucune'}",
        (
            f"Format : arc {' → '.join(plan.arc)} ; {plan.min_total_seconds}-{plan.max_total_seconds} s ; "
            f"plans de {plan.min_shot_seconds}-{plan.max_shot_seconds} s ; "
            f"plans muets : {silent}"
        ),
        f"Avatar : {agent.avatar.name or '—'} · image {agent.avatar.avatar_url or 'aucune'}",
        f"Apparence : {agent.avatar.appearance or '—'}",
        f"Voix : {agent.avatar.voice_url or 'aucune'}",
    ]
    return "\n".join(lines)


def build_tools(session, studio: Studio) -> list:
    """Les outils, fermés sur la conversation et le Studio de cette requête.

    LangChain exécute en parallèle les appels d'outils d'un même message : un verrou les
    passe un par un, sinon deux `set_…` simultanés s'écraseraient le brouillon.
    """
    lock = threading.Lock()

    def guarded(fn: Callable[..., str]) -> Callable[..., str]:
        @functools.wraps(fn)
        def run(*args: Any, **kwargs: Any) -> str:
            with lock:
                try:
                    return fn(*args, **kwargs)
                # Tout, pas seulement STUDIO_ERRORS : une exception qui sortirait d'un outil
                # ferait échouer le tour entier, au lieu de dire au modèle quoi corriger.
                except Exception as exc:  # noqa: BLE001
                    log.warning("Outil %s : %s", fn.__name__, exc)
                    return f"Échec : {explain(exc)}"

        return run

    def draft() -> ChannelIn:
        return session.draft or blank_channel()

    def update(changes: dict) -> str:
        merged = _merge(draft().model_dump(mode="json"), changes)
        session.draft = ChannelIn.model_validate(merged)
        blocking, _ = readiness(session.draft)
        return "Brouillon mis à jour." + (
            f" Encore {len(blocking)} point(s) bloquant(s) : check_draft pour le détail." if blocking else ""
        )

    def storage() -> Storage:
        if studio.storage is None:
            raise HTTPException(503, "Le bucket n'est pas configuré sur ce Studio (SCW_ACCESS_KEY, SCW_SECRET_KEY).")
        return studio.storage

    def checked_image(uri: str, kinds: dict[str, str]) -> str:
        uri = uri.strip()
        key = bucket_key(uri)
        if key is None or PurePosixPath(key).suffix.lower() not in kinds:
            raise ValueError(f"{uri} n'est pas une image du bucket ({', '.join(sorted(kinds))}).")
        if not storage().exists(key):
            raise ValueError(f"{uri} est introuvable dans le bucket : prends une URI de list_images.")
        return uri

    # --- Lire ---

    @tool
    @guarded
    def list_channels() -> str:
        """Les channels du Studio : identifiant, nom, langue, version et paramètres de run."""
        loaded = [from_document(document) for document in studio.channels.find().sort("name", 1)]
        if not loaded:
            return "Aucun channel pour l'instant."
        return "\n".join(
            f"- {c.id} « {c.name} » ({c.agent_config.language or 'langue libre'}, v{c.version}) : "
            f"{c.description or 'sans description'} | paramètres : "
            f"{', '.join(f'{p.name}:{p.type}' for p in c.parameters) or 'aucun'}"
            for c in loaded
        )

    @tool
    @guarded
    def get_channel(channel_id: str) -> str:
        """Charge un channel enregistré dans le brouillon, pour le modifier ou y proposer des runs.

        Remplace le brouillon en cours : enregistre-le d'abord s'il faut le garder.
        """
        channel = load_channel(studio, channel_id)
        if channel is None:
            return f"Channel {channel_id} introuvable. list_channels donne les identifiants."
        session.draft = as_draft(channel)
        session.base_version = channel.version
        return "Chargé dans le brouillon :\n" + describe(session.draft, session.base_version)

    @tool
    @guarded
    def catalog() -> str:
        """Les langues, les styles et les réglages par défaut d'un channel neuf."""
        skills = json.loads(SKILLS_FILE.read_text("utf-8")) if SKILLS_FILE.exists() else []
        defaults = blank_channel().agent_config
        styles = [f"- {s['name']} ({s.get('tag', '')}) : {s.get('summary', '')}" for s in skills]
        publication = defaults.publication
        return "\n".join(
            [
                "Langues : " + ", ".join(f"{code} ({name})" for code, name in LANGUAGE_NAMES.items()),
                "Styles (skill) :",
                *styles,
                '- "" : libre, le réalisateur choisit sa méthode (le cas d\'une fiction).',
                (
                    f"Format par défaut : arc {' → '.join(defaults.plan.arc)} ; "
                    f"{defaults.plan.min_total_seconds}-{defaults.plan.max_total_seconds} s ; "
                    f"plans de {defaults.plan.min_shot_seconds}-{defaults.plan.max_shot_seconds} s."
                ),
                (
                    f"Publication : titre {publication.min_title_chars}-{publication.max_title_chars} caractères, "
                    f"légende {publication.min_chars}-{publication.max_chars}, "
                    f"{publication.min_hashtags}-{publication.max_hashtags} hashtags."
                ),
            ]
        )

    @tool
    @guarded
    def list_images(kind: Literal["avatar", "reference"]) -> str:
        """Les images déjà dans le bucket, pour en reprendre une plutôt que d'en refaire une.

        kind: "avatar" (images et vidéos d'avatar) ou "reference" (images de référence).
        """
        items = avatars(storage()) if kind == "avatar" else references(storage())
        if not items:
            return "Aucune image de ce type dans le bucket."
        lines = [f"- {item['name']} ({item['kind']}) : {item['uri']}" for item in items[:LISTED]]
        if len(items) > LISTED:
            lines.append(f"… et {len(items) - LISTED} autres, plus anciennes.")
        return "\n".join(lines)

    @tool
    @guarded
    def find_voices(language: str, sex: Literal["male", "female"] | None = None, age_range: str | None = None) -> str:
        """Les voix du catalogue dans une langue, avec la description de chacune.

        language: code de la langue du channel (ex. "fr") : la voix fixe aussi l'accent.
        sex: "male" ou "female", facultatif.
        age_range: tranche d'âge, ex. "20-30", "40-50", facultatif.
        """
        catalog_ = list(voice_catalog(storage()).values())
        found = [
            voice
            for voice in catalog_
            if voice["language"] == language
            and (sex is None or voice["sex"] == sex)
            and (age_range is None or voice["age_range"] == age_range)
        ]
        if not found:
            languages = sorted({voice["language"] for voice in catalog_})
            ages = sorted({voice["age_range"] for voice in catalog_ if voice["language"] == language})
            return (
                f"Aucune voix pour ce filtre. Langues du catalogue : {', '.join(languages) or 'aucune'}. "
                f"Tranches d'âge en {language} : {', '.join(ages) or 'aucune'}."
            )
        lines = []
        for voice in found[:LISTED]:
            sheet = voice_sheet(storage(), voice["uri"])
            lines.append(
                f"- {voice['name']} ({voice['sex']}, {voice['age_range']}) : {voice['uri']}"
                + (f"\n  {sheet['description']}" if sheet.get("description") else "")
            )
        return "\n".join(lines)

    # --- Construire le brouillon ---

    @tool
    @guarded
    def set_identity(
        channel_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        language: str | None = None,
        channel_name: str | None = None,
        email: str | None = None,
        skill: str | None = None,
    ) -> str:
        """Fixe l'identité du channel. Seuls les champs passés changent.

        channel_id: l'identifiant, 2 à 40 caractères, minuscules, chiffres et tirets
            (ex. "herisson-boulanger"). Il préfixe chaque run et ne change plus une fois
            le channel enregistré.
        name: le nom affiché dans le Studio.
        description: une phrase qui dit ce qu'est le channel.
        language: code de la langue des vidéos (ex. "fr").
        channel_name: le dossier de publication des vidéos (ex. "pico-boulanger").
        email: l'adresse qui reçoit chaque vidéo et chaque échec. Demande-la, ne l'invente pas.
        skill: le style de production ; "" pour libre (le cas d'une fiction).
        """
        if channel_id is not None and session.base_version is not None and channel_id != draft().id:
            return "L'identifiant d'un channel enregistré ne change pas."
        if language is not None and language and language not in LANGUAGE_NAMES:
            return f"Langue inconnue. Codes possibles : {', '.join(LANGUAGE_NAMES)}."
        changes: dict[str, Any] = {}
        for key, value in (("id", channel_id), ("name", name), ("description", description)):
            if value is not None:
                changes[key] = value.strip()
        config = {key: value.strip() for key, value in (("channel_name", channel_name), ("email", email)) if value is not None}
        if config:
            changes["channel_config"] = config
        agent = {key: value.strip() for key, value in (("language", language), ("skill", skill)) if value is not None}
        if agent:
            changes["agent_config"] = agent
        return update(changes)

    @tool
    @guarded
    def set_brief(
        prompt: str | None = None,
        mood: str | None = None,
        parameters: list[ChannelParameter] | None = None,
        must_include: list[str] | None = None,
    ) -> str:
        """Fixe le brief, le mood, les paramètres de run et les mentions obligatoires.

        prompt: le brief que le réalisateur reçoit pour chaque vidéo. Il porte le format,
            le personnage (nom, caractère, façon de parler) et cite chaque paramètre par
            ${nom}. Jamais de physique, de tenue ni d'accessoire.
        mood: le ton et l'énergie.
        parameters: TOUS les paramètres de run (la liste remplace l'ancienne). Nom en
            minuscules (ex. idee) ; type "string" (une ligne), "text", "url", "number",
            "boolean" ou "image" ; required ; default ; description.
        must_include: chaînes courtes recopiées telles quelles dans la légende.
        """
        brief = {key: value for key, value in (("prompt", prompt), ("mood", mood)) if value is not None}
        agent: dict[str, Any] = {"brief": brief} if brief else {}
        if must_include is not None:
            agent["publication"] = {"must_include": [item.strip() for item in must_include if item.strip()]}
        changes: dict[str, Any] = {"agent_config": agent} if agent else {}
        if parameters is not None:
            changes["parameters"] = [
                parameter.model_dump() if isinstance(parameter, BaseModel) else parameter for parameter in parameters
            ]
        return update(changes)

    @tool
    @guarded
    def set_format(
        arc: list[str] | None = None,
        min_total_seconds: int | None = None,
        max_total_seconds: int | None = None,
        min_shot_seconds: int | None = None,
        max_shot_seconds: int | None = None,
        max_silent_shots: int | None = None,
    ) -> str:
        """Fixe le format des vidéos : l'arc narratif, les durées, les plans muets.

        arc: les rôles des plans, dans l'ordre ; le premier ouvre la vidéo, le dernier la
            ferme (ex. ["hook", "situation", "peripetie", "chute"]).
        min_total_seconds, max_total_seconds: la durée totale visée.
        min_shot_seconds, max_shot_seconds: la durée d'un plan (le moteur accepte 5 à 15 s).
        max_silent_shots: combien de plans peuvent se passer de réplique (l'avatar y est
            à l'écran sans parler : un geste, une réaction). 0 : il parle dans chaque plan.
        """
        current = draft().agent_config.plan
        roles = [role.strip() for role in arc] if arc is not None else list(current.arc)
        low_total = current.min_total_seconds if min_total_seconds is None else min_total_seconds
        high_total = current.max_total_seconds if max_total_seconds is None else max_total_seconds
        low_shot = current.min_shot_seconds if min_shot_seconds is None else min_shot_seconds
        high_shot = current.max_shot_seconds if max_shot_seconds is None else max_shot_seconds
        engine_low, engine_high = ENGINE_SHOT_SECONDS
        if len(roles) < 2 or not all(roles) or len(set(roles)) != len(roles):
            return "L'arc demande au moins deux rôles, distincts et non vides."
        if not engine_low <= low_shot <= high_shot <= engine_high:
            return f"Durée d'un plan : il faut {engine_low} ≤ min ≤ max ≤ {engine_high} s (le moteur)."
        if not 0 < low_total <= high_total:
            return "Durée totale : il faut 0 < min ≤ max."
        # Le premier et le dernier rôle sont imposés : au moins deux plans.
        possible = [n for n in range(2, high_total // low_shot + 1) if n * high_shot >= low_total]
        if not possible:
            return (
                f"Format impossible : aucun nombre de plans de {low_shot}-{high_shot} s ne tombe "
                f"dans {low_total}-{high_total} s. Élargis l'une des deux fourchettes."
            )
        silent = current.max_silent_shots if max_silent_shots is None else max_silent_shots
        # Le réalisateur exige au moins un plan parlé : il en faut un de plus que de muets.
        if not 0 <= silent < max(possible):
            return f"Plans muets : entre 0 et {max(possible) - 1}, pour qu'au moins un plan parle."
        return update(
            {
                "agent_config": {
                    "plan": {
                        "arc": roles,
                        "min_total_seconds": low_total,
                        "max_total_seconds": high_total,
                        "min_shot_seconds": low_shot,
                        "max_shot_seconds": high_shot,
                        "max_silent_shots": silent,
                    }
                }
            }
        )

    @tool
    @guarded
    def set_avatar(
        name: str | None = None,
        appearance_en: str | None = None,
        description: str | None = None,
        avatar_uri: str | None = None,
    ) -> str:
        """Fixe l'avatar : son nom, son apparence, son rôle, et l'image s'il en reprend une.

        name: le nom du personnage (ex. "Pico").
        appearance_en: en anglais, 15 à 40 mots, un groupe nominal qui décrit ce qu'on
            voit sur l'image et qui ne change pas d'un plan à l'autre : espèce ou type,
            âge, carrure, couleurs, pelage ou cheveux, tenue, style de rendu. Ni pose, ni
            expression, ni décor.
        description: son rôle en quelques mots (ex. "boulanger du village, narrateur").
        avatar_uri: une image ou vidéo déjà dans le bucket (list_images). Une image neuve
            arrive par la carte request_image, pas par ici.
        """
        avatar: dict[str, Any] = {}
        if name is not None:
            avatar["name"] = name.strip()
        if description is not None:
            avatar["description"] = description.strip()
        if appearance_en is not None:
            words = len(appearance_en.split())
            if words > MAX_APPEARANCE_WORDS:
                return f"Apparence trop longue ({words} mots) : 15 à 40 mots, l'essentiel visible et stable."
            avatar["appearance"] = appearance_en.strip()
        if avatar_uri is not None:
            avatar["avatar_url"] = checked_image(avatar_uri, {**IMAGE_TYPES, **VIDEO_TYPES})
            avatar["reference_frame_s"] = None
        return update({"agent_config": {"avatar": avatar}}) if avatar else "Rien à changer."

    @tool
    @guarded
    def set_voice(voice_uri: str) -> str:
        """Fixe la voix de l'avatar, prise dans le catalogue (find_voices).

        voice_uri: l'URI s3:// de la voix.
        """
        voice = voice_catalog(storage()).get(voice_uri.strip())
        if voice is None:
            return "Cette voix n'est pas dans le catalogue : prends une URI donnée par find_voices."
        language = draft().agent_config.language
        if language and voice["language"] != language:
            return f"Cette voix est en {voice['language']}, le channel en {language} : l'accent suivrait la voix."
        return update({"agent_config": {"avatar": {"voice_url": voice["uri"]}}})

    @tool
    @guarded
    def check_draft() -> str:
        """Le brouillon en clair, ce qui bloque son enregistrement, et ce que le réalisateur recevra."""
        current = draft()
        blocking, advice = readiness(current)
        rendered = preview(current, {})
        lines = [describe(current, session.base_version), ""]
        lines.append("Bloquant :" if blocking else "Rien ne bloque l'enregistrement.")
        lines += [f"- {line}" for line in blocking]
        if advice:
            lines.append("À considérer :")
            lines += [f"- {line}" for line in advice]
        lines += ["", "Message que le réalisateur recevra (valeurs par défaut) :", rendered["user_message"][:3000]]
        return "\n".join(lines)

    # --- Cartes ---

    @tool
    @guarded
    def request_image(
        purpose: Literal["avatar", "reference"],
        name: str,
        prompt_en: str,
        why: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> str:
        """Pose une carte qui demande une image : l'utilisateur la génère avec ce prompt et la dépose.

        purpose: "avatar" (l'image du personnage, fixe pour le channel) ou "reference"
            (une autre image : un invité, un objet, un décor).
        name: comment s'appelle ce qu'elle montre (ex. "Pico", "invite-renard").
        prompt_en: le prompt de génération, en anglais, détaillé. Pour un avatar : une
            seule image verticale 9:16, un seul sujet, visage bien visible, pose neutre
            face caméra, fond simple et opaque, tenue simple, aucun texte ni logo, PNG.
        why: une phrase pour l'utilisateur sur ce que l'image doit réussir.
        """
        payload = {"purpose": purpose, "name": name.strip(), "prompt": prompt_en.strip(), "why": why.strip()}
        session.add_card("image", payload, tool_call_id)
        return (
            "Carte posée. L'utilisateur génère l'image puis la dépose sur la carte : une note "
            "[Studio] te l'apportera. Arrête-toi là, ne fais pas comme si elle était arrivée."
        )

    @tool
    @guarded
    def suggest_voices(voice_uris: list[str], why: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> str:
        """Pose une carte avec 1 à 3 voix à écouter : l'utilisateur en choisit une.

        voice_uris: les URI données par find_voices.
        why: une phrase sur ce qui rapproche ces voix du personnage.
        """
        known = voice_catalog(storage())
        uris = list(dict.fromkeys(uri.strip() for uri in voice_uris))
        if not 1 <= len(uris) <= 3:
            return "Propose 1 à 3 voix."
        unknown = [uri for uri in uris if uri not in known]
        if unknown:
            return f"Pas dans le catalogue : {', '.join(unknown)}. Prends les URI de find_voices."
        session.add_card("voices", {"uris": uris, "why": why.strip()}, tool_call_id)
        return "Carte posée : l'utilisateur écoute et choisit. Une note [Studio] te dira laquelle."

    @tool
    @guarded
    def propose_channel(tool_call_id: Annotated[str, InjectedToolCallId]) -> str:
        """Pose la carte « Channel prêt » : l'utilisateur enregistre le brouillon d'un clic.

        Refusée tant qu'un point bloque (voir check_draft).
        """
        if session.draft is None:
            return "Le brouillon est vide."
        blocking, advice = readiness(session.draft)
        if blocking:
            return "Pas encore enregistrable :\n" + "\n".join(f"- {line}" for line in blocking)
        payload = {"channel": session.draft.model_dump(mode="json"), "base_version": session.base_version, "advice": advice}
        session.add_card("channel", payload, tool_call_id)
        return "Carte posée : l'utilisateur enregistre d'un clic. Une note [Studio] te donnera le résultat."

    @tool
    @guarded
    def propose_runs(
        channel_id: str, candidates: list[RunCandidate], tool_call_id: Annotated[str, InjectedToolCallId]
    ) -> str:
        """Pose une carte de runs candidats : l'utilisateur coche ceux qui partent dans la file.

        channel_id: un channel enregistré.
        candidates: les runs, chacun avec son pitch (une ligne) et ses values, la valeur de
            chaque paramètre du channel par son nom. Une image : une URI de list_images ou
            d'une image déposée, jamais inventée.
        """
        channel = load_channel(studio, channel_id)
        if channel is None:
            return f"Channel {channel_id} introuvable : il doit être enregistré avant d'y lancer des runs."
        if not candidates or len(candidates) > MAX_CANDIDATES:
            return f"Propose 1 à {MAX_CANDIDATES} runs."
        if not channel.agent_config.avatar.avatar_url:
            return "Ce channel n'a pas d'avatar : aucun run ne partirait. Règle l'avatar d'abord."
        parsed = [c if isinstance(c, RunCandidate) else RunCandidate.model_validate(c) for c in candidates]
        images = {parameter.name for parameter in channel.parameters if parameter.type == "image"}
        problems: list[str] = []
        for number, candidate in enumerate(parsed, start=1):
            if not candidate.pitch.strip():
                problems.append(f"n°{number} : le pitch est vide.")
            _, issues = resolve_values(channel, candidate.values)
            problems += [f"n°{number} : {_issue_text(item)}" for item in issues]
            for name in images & candidate.values.keys():
                try:
                    checked_image(candidate.values[name], IMAGE_TYPES)
                except STUDIO_ERRORS as exc:
                    problems.append(f"n°{number} : {name} : {explain(exc)}")
        if problems:
            return "Carte non posée, à corriger :\n" + "\n".join(f"- {line}" for line in problems)
        listed = [{"n": number, **candidate.model_dump()} for number, candidate in enumerate(parsed, start=1)]
        payload = {"channel_id": channel.id, "channel_name": channel.name, "channel_version": channel.version, "candidates": listed}
        session.add_card("runs", payload, tool_call_id)
        return f"Carte posée avec {len(listed)} runs : l'utilisateur coche ceux qu'il ajoute à la file."

    return [
        list_channels,
        get_channel,
        catalog,
        list_images,
        find_voices,
        set_identity,
        set_brief,
        set_format,
        set_avatar,
        set_voice,
        check_draft,
        request_image,
        suggest_voices,
        propose_channel,
        propose_runs,
    ]
