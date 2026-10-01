"""Un channel : une config de base, éditée en place, depuis laquelle on lance des runs.

Le channel porte ce qu'un opérateur choisit (brief, avatar, voix, style, modèles,
paramètres de run). Il ne porte jamais de secret ni de réglage de la machine du worker :
`base_url`, tokens, scraper, stockage et chemins de sortie sont remplis au lancement,
côté serveur (`app/render.py`).

En base, le document est creux : seuls les champs qui diffèrent des valeurs par défaut
sont écrits. Un défaut amélioré dans le worker profite donc aux channels qui ne le
surchargent pas ; chaque run, lui, reste un instantané complet.
"""

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.issues import Loc, issue, strings
from app.params import PARAM_NAME, TOKEN, ParamType, coerce, is_empty, scan
from app.storage import BUCKET, bucket_key
from app.task_config import (
    LANGUAGE_NAMES,
    PROVIDERS,
    Avatar,
    Brief,
    ChannelConfig,
    LLMSettings,
    PlanConstraints,
    PublicationConstraints,
    RenderSettings,
    SubtitleSettings,
)

SLUG = re.compile(r"[a-z0-9][a-z0-9-]{1,39}")
"""L'identifiant du channel : il préfixe le `task_id` de ses runs, qui devient un dossier."""

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

AVATAR_URL: Loc = ("agent_config", "avatar", "avatar_url")
TEMPLATED: tuple[Loc, ...] = (
    ("agent_config", "brief", "prompt"),
    ("agent_config", "brief", "mood"),
    ("agent_config", "publication", "must_include"),
    AVATAR_URL,
    ("agent_config", "avatar", "name"),
    ("agent_config", "avatar", "description"),
    ("agent_config", "avatar", "appearance"),
)
"""Les seuls champs où `${nom}` est remplacé par la valeur du run."""

IMAGE_CITABLE: tuple[Loc, ...] = (("agent_config", "brief", "prompt"), ("agent_config", "brief", "mood"))
"""Où une image se cite par son label (`<Subject 2>`). Ailleurs, seule l'image de
l'avatar en accepte une, citée seule : `${personnage}`."""


class ChannelParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: ParamType = "string"
    default: str = ""
    required: bool = False
    description: str = ""


class ModelChoice(BaseModel):
    """Un modèle : le fournisseur (et donc son adresse et sa clé) et le nom du déploiement."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model_name: str


class ChannelModels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    master_mind: ModelChoice = ModelChoice(provider="foundry", model_name="claude-opus-4-7-1")
    """Le réalisateur : lit les skills, écrit le plan de tournage."""
    slm: ModelChoice = ModelChoice(provider="foundry", model_name="claude-haiku-4-5")
    """Le petit modèle : explique les échecs dans l'e-mail."""
    video_generator: ModelChoice = ModelChoice(provider="sglang", model_name="MiniMaxAI/MiniMax-H3")
    """Le moteur vidéo. Sert aussi d'`image_generator`, que le worker ne lit pas."""


def _blank_avatar() -> Avatar:
    return Avatar(name="", avatar_url="", description="", appearance="")


class ChannelAgent(BaseModel):
    """La partie éditable d'`AgentConfig`."""

    model_config = ConfigDict(extra="forbid")

    skill: str = ""
    language: str = ""
    brief: Brief = Field(default_factory=lambda: Brief(prompt=""))
    avatar: Avatar = Field(default_factory=_blank_avatar)
    models: ChannelModels = Field(default_factory=ChannelModels)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    render: RenderSettings = Field(default_factory=RenderSettings)
    plan: PlanConstraints = Field(default_factory=PlanConstraints)
    publication: PublicationConstraints = Field(default_factory=PublicationConstraints)
    subtitles: SubtitleSettings = Field(default_factory=SubtitleSettings)


class ChannelIn(BaseModel):
    """Un channel tel que l'éditeur l'envoie."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    channel_config: ChannelConfig
    parameters: list[ChannelParameter] = Field(default_factory=list)
    agent_config: ChannelAgent = Field(default_factory=ChannelAgent)


class ChannelUpdate(ChannelIn):
    version: int
    """La version que l'éditeur a chargée : périmée, l'enregistrement est refusé (409)."""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    """Renvoyés tels quels par l'éditeur, ignorés : c'est le serveur qui date."""


class Channel(ChannelIn):
    version: int
    created_at: datetime
    updated_at: datetime


def validate_channel(channel: ChannelIn) -> tuple[list[dict], list[dict]]:
    """(erreurs, avertissements). Une erreur bloque l'enregistrement, un avertissement non."""
    errors: list[dict] = []
    warnings: list[dict] = []
    data = channel.model_dump(mode="json")
    agent = channel.agent_config

    if not SLUG.fullmatch(channel.id):
        errors.append(issue(("id",), "2 à 40 caractères : minuscules, chiffres et -, sans commencer par -.", channel.id))
    if not channel.name.strip():
        errors.append(issue(("name",), "Donne un nom au channel.", channel.name))
    if not re.search(r"[A-Za-z0-9]", channel.channel_config.channel_name):
        errors.append(issue(("channel_config", "channel_name"), "Le dossier de publication doit contenir au moins une lettre ou un chiffre.", channel.channel_config.channel_name))
    if not EMAIL.match(channel.channel_config.email):
        errors.append(issue(("channel_config", "email"), "Adresse e-mail invalide : c'est elle qui reçoit chaque vidéo.", channel.channel_config.email))

    declared: dict[str, ChannelParameter] = {}
    for index, parameter in enumerate(channel.parameters):
        loc = ("parameters", index)
        if not PARAM_NAME.fullmatch(parameter.name):
            errors.append(issue((*loc, "name"), "Minuscules, chiffres et _, en commençant par une lettre (ex. source_url).", parameter.name))
        elif parameter.name in declared:
            errors.append(issue((*loc, "name"), f"Deux paramètres s'appellent {parameter.name}.", parameter.name))
        else:
            declared[parameter.name] = parameter
        if not is_empty(parameter.default):
            try:
                coerce(parameter.type, parameter.default)
            except ValueError as exc:
                errors.append(issue((*loc, "default"), f"Valeur par défaut : {exc}", parameter.default))

    used: set[str] = set()
    templated = {loc for loc in TEMPLATED}
    for loc, text in strings(data):
        in_template = loc[:3] in templated or loc in templated
        if not in_template:
            if "${" in text:
                errors.append(issue(loc, "${…} n'est remplacé que dans le brief, le mood, les mentions obligatoires et l'avatar.", text))
            continue
        names, malformed = scan(text)
        for fragment in malformed:
            errors.append(issue(loc, f"« {fragment} » : un paramètre s'écrit ${{nom}}, en minuscules (ex. ${{source_url}}).", text))
        for name in names:
            used.add(name)
            if name not in declared:
                errors.append(issue(loc, f"${{{name}}} n'est pas déclaré : ajoute-le dans Paramètres.", text))
            elif declared[name].type == "image" and loc[:3] not in IMAGE_CITABLE and loc != AVATAR_URL:
                errors.append(issue(loc, f"${{{name}}} est une image : elle se cite dans le brief, le mood, ou comme image de l'avatar.", text))
        if loc == AVATAR_URL and names:
            bound = avatar_parameter(channel)
            if bound is None or (bound in declared and declared[bound].type != "image"):
                errors.append(issue(loc, "L'image de l'avatar vient du bucket, ou d'un paramètre de type image cité seul (ex. ${personnage}).", text))

    for index, parameter in enumerate(channel.parameters):
        # Une image non citée sert quand même : elle part au moteur comme référence.
        if parameter.name in declared and parameter.name not in used and parameter.type != "image":
            warnings.append(issue(("parameters", index, "name"), f"{parameter.name} n'est cité nulle part : l'agent le reçoit seulement dans « SUJET PRÉCIS ».", parameter.name))

    if agent.language and agent.language not in LANGUAGE_NAMES:
        errors.append(issue(("agent_config", "language"), f"Langue inconnue : {agent.language}.", agent.language))

    for role, choice in agent.models:
        loc = ("agent_config", "models", role)
        if choice.provider not in PROVIDERS:
            errors.append(issue((*loc, "provider"), f"Fournisseur inconnu. Connus : {', '.join(PROVIDERS)}.", choice.provider))
        if not choice.model_name.strip():
            errors.append(issue((*loc, "model_name"), "Nom du modèle manquant.", choice.model_name))

    for field, required in (("avatar_url", True), ("voice_url", False)):
        uri = getattr(agent.avatar, field)
        loc = ("agent_config", "avatar", field)
        if is_empty(uri):
            if required:
                warnings.append(issue(loc, "Pas encore d'avatar : il en faudra un pour lancer un run.", uri))
        elif "${" not in uri and bucket_key(uri) is None:
            errors.append(issue(loc, f"Choisis un fichier du bucket (s3://{BUCKET}/…) : une adresse extérieure serait téléchargée par la machine GPU.", uri))
    if agent.avatar.avatar_url and not agent.avatar.appearance.strip():
        warnings.append(issue(("agent_config", "avatar", "appearance"), "Sans apparence décrite, rien ne verrouille la tenue d'un plan à l'autre.", ""))

    return errors, warnings


def avatar_parameter(channel: ChannelIn) -> str | None:
    """Le paramètre qui fournit l'image de l'avatar à chaque run (`avatar_url` = `${nom}`).

    Le héros change d'un run à l'autre, le channel reste le même : c'est le run qui
    apporte son image, et elle devient `<Subject 1>`.
    """
    match = TOKEN.fullmatch(channel.agent_config.avatar.avatar_url.strip())
    return match[1] if match else None


def normalized(channel: ChannelIn) -> ChannelIn:
    """Le channel avec les réglages de la machine du worker remis à leur valeur.

    Les chemins de sortie et le binaire ffmpeg sont ceux de la machine qui exécute :
    ils ne s'éditent pas depuis l'interface.
    """
    agent = channel.agent_config
    render = agent.render.model_copy(
        update={"output_dir": RenderSettings().output_dir, "final_name": RenderSettings().final_name}
    )
    subtitles = agent.subtitles.model_copy(update={"ffmpeg_bin": SubtitleSettings().ffmpeg_bin})
    return channel.model_copy(
        update={"agent_config": agent.model_copy(update={"render": render, "subtitles": subtitles})}
    )


def to_document(channel: ChannelIn, *, version: int, created_at: datetime, updated_at: datetime) -> dict:
    data = channel.model_dump(mode="python", exclude={"agent_config"})
    data["_id"] = data.pop("id")
    data["agent_config"] = channel.agent_config.model_dump(mode="python", exclude_defaults=True)
    return {**data, "version": version, "created_at": created_at, "updated_at": updated_at}


def from_document(document: dict[str, Any]) -> Channel:
    data = dict(document)
    data["id"] = data.pop("_id")
    return Channel.model_validate(data)
