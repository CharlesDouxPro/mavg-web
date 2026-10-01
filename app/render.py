"""D'un channel et des valeurs d'un run à la tâche que le worker recevra.

La tâche est un instantané complet : modifier le channel ensuite ne la change pas. Les
secrets n'y figurent que sous forme de référence (`${FOUNDRY_API_KEY}`), résolue par le
worker ; l'adresse de chaque fournisseur vient du registre partagé, jamais du channel.

Les paramètres `image` ne vont pas dans `params` : ils deviennent l'image de l'avatar
(`avatar_url` = `${nom}`) ou une référence de plus (`agent_config.references`), que le
worker envoie au moteur avec chaque plan.
"""

import secrets
from datetime import datetime
from typing import Any

from app.channels import Channel, ChannelIn, ModelChoice, avatar_parameter
from app.issues import issue
from app.params import as_text, coerce, is_empty, render
from app.task_config import (
    PROVIDERS,
    SCHEMA_VERSION,
    SCRAPERS,
    AgentConfig,
    Brief,
    ModelConfig,
    ModelConfigs,
    ReferenceImage,
    ScraperConfig,
    StorageConfig,
    TaskConfig,
    check_secret_destinations,
    reference_number,
)


def resolve_values(channel: ChannelIn, submitted: dict[str, Any]) -> tuple[dict[str, str], list[dict]]:
    """Les valeurs du run, typées puis écrites en texte, et les erreurs par paramètre.

    Absente ou nulle, une valeur prend le défaut du channel. Vide, un paramètre facultatif
    est simplement omis — sauf celui qui fournit l'avatar : sans lui, pas de vidéo.
    """
    issues: list[dict] = []
    declared = {parameter.name: parameter for parameter in channel.parameters}
    bound = avatar_parameter(channel)
    for name, raw in submitted.items():
        if name not in declared:
            issues.append(issue(("values", name), f"{name} n'est pas un paramètre de ce channel.", raw))

    values: dict[str, str] = {}
    for name, parameter in declared.items():
        raw = submitted.get(name)
        if raw is None:
            raw = parameter.default
        loc = ("values", name)
        if is_empty(raw):
            if name == bound:
                issues.append(issue(loc, "Paramètre requis : c'est l'image de l'avatar.", raw))
            elif parameter.required:
                issues.append(issue(loc, "Paramètre requis.", raw))
            continue
        if isinstance(raw, str) and "${" in raw:
            issues.append(issue(loc, "Une valeur ne peut pas contenir « ${ ».", raw))
            continue
        try:
            values[name] = as_text(coerce(parameter.type, raw))
        except ValueError as exc:
            issues.append(issue(loc, str(exc), raw))
    return values, issues


def _model(choice: ModelChoice) -> ModelConfig:
    provider = PROVIDERS[choice.provider]
    return ModelConfig(
        provider=choice.provider,
        model_name=choice.model_name,
        base_url=provider["base_url"],
        token=provider["token"],
    )


def references(channel: ChannelIn, values: dict[str, str]) -> list[ReferenceImage]:
    """Les images du run hors avatar, dans l'ordre des paramètres : leur ordre fixe leur label."""
    bound = avatar_parameter(channel)
    return [
        ReferenceImage(name=parameter.name, image_url=values[parameter.name], description=parameter.description)
        for parameter in channel.parameters
        if parameter.type == "image" and parameter.name != bound and parameter.name in values
    ]


def build_agent(channel: ChannelIn, values: dict[str, str], keep_missing: bool = False) -> AgentConfig:
    agent = channel.agent_config
    images = {parameter.name for parameter in channel.parameters if parameter.type == "image"}
    texts = {name: value for name, value in values.items() if name not in images}
    extra = references(channel, values)
    # Une image se cite par son label : c'est ainsi que l'agent désigne le sujet dans ses plans.
    labels = {reference.name: f"<Subject {reference_number(i)}>" for i, reference in enumerate(extra)}
    if bound := avatar_parameter(channel):
        labels[bound] = "<Subject 1>"

    def fill(text: str) -> str:
        return render(text, {**texts, **labels}, keep_missing)

    avatar = agent.avatar.model_copy(
        update={
            "avatar_url": render(agent.avatar.avatar_url.strip(), values, keep_missing),
            "name": fill(agent.avatar.name),
            "description": fill(agent.avatar.description),
            "appearance": fill(agent.avatar.appearance),
        }
    )
    must_include = [text for item in agent.publication.must_include if (text := fill(item).strip())]
    return AgentConfig(
        params=texts,
        models=ModelConfigs(
            master_mind=_model(agent.models.master_mind),
            slm=_model(agent.models.slm),
            video_generator=_model(agent.models.video_generator),
            image_generator=_model(agent.models.video_generator),
        ),
        skill=agent.skill,
        language=agent.language,
        brief=Brief(prompt=fill(agent.brief.prompt), mood=fill(agent.brief.mood)),
        avatar=avatar,
        references=extra,
        llm=agent.llm,
        render=agent.render,
        plan=agent.plan,
        scraper=ScraperConfig(token=SCRAPERS[ScraperConfig().provider]["token"]),
        storage=StorageConfig(access_key="${SCW_ACCESS_KEY}", secret_key="${SCW_SECRET_KEY}"),
        publication=agent.publication.model_copy(update={"must_include": must_include}),
        subtitles=agent.subtitles,
    )


def new_task_id(channel_id: str, now: datetime) -> str:
    """`<channel>_<aammjj-hhmmss>_<4 hex>` : unique même pour deux lancements dans la seconde."""
    return f"{channel_id}_{now:%y%m%d-%H%M%S}_{secrets.token_hex(2)}"


def build_document(channel: Channel, values: dict[str, str], now: datetime) -> dict:
    """Le document inséré dans la file : la tâche complète, plus sa provenance."""
    task = TaskConfig(
        created_at=now,
        task_id=new_task_id(channel.id, now),
        status="pending",
        channel_config=channel.channel_config,
        agent_config=build_agent(channel, values),
    )
    document = task.model_dump()
    # La même garde que le worker : une tâche qu'il refuserait ne part pas.
    check_secret_destinations(document)
    document.update(
        channel_id=channel.id,
        channel_label=channel.name,
        channel_version=channel.version,
        run_params=values,
        schema_version=SCHEMA_VERSION,
    )
    return document


def preview(channel: ChannelIn, submitted: dict[str, Any]) -> dict:
    """Ce que l'agent recevra, sans rien insérer. Un paramètre sans valeur reste `${nom}`."""
    values, issues = resolve_values(channel, submitted)
    agent = build_agent(channel, values, keep_missing=True)
    cited = {parameter.name for parameter in channel.parameters}
    return {
        "prompt": agent.brief.prompt,
        "mood": agent.brief.mood,
        "must_include": agent.publication.must_include,
        "user_message": agent.user_message(),
        "missing": sorted(name for name in cited if name not in values),
        "issues": issues,
    }
