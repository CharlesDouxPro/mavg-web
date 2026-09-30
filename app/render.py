"""D'un channel et des valeurs d'un run à la tâche que le worker recevra.

La tâche est un instantané complet : modifier le channel ensuite ne la change pas. Les
secrets n'y figurent que sous forme de référence (`${FOUNDRY_API_KEY}`), résolue par le
worker ; l'adresse de chaque fournisseur vient du registre partagé, jamais du channel.
"""

import secrets
from datetime import datetime
from typing import Any

from app.channels import Channel, ChannelIn, ModelChoice
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
    ScraperConfig,
    StorageConfig,
    TaskConfig,
    check_secret_destinations,
)


def resolve_values(channel: ChannelIn, submitted: dict[str, Any]) -> tuple[dict[str, str], list[dict]]:
    """Les valeurs du run, typées puis écrites en texte, et les erreurs par paramètre.

    Absente ou nulle, une valeur prend le défaut du channel. Vide, un paramètre facultatif
    est simplement omis.
    """
    issues: list[dict] = []
    declared = {parameter.name: parameter for parameter in channel.parameters}
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
            if parameter.required:
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


def build_agent(channel: ChannelIn, values: dict[str, str], keep_missing: bool = False) -> AgentConfig:
    agent = channel.agent_config

    def fill(text: str) -> str:
        return render(text, values, keep_missing)

    must_include = [text for item in agent.publication.must_include if (text := fill(item).strip())]
    return AgentConfig(
        params=dict(values),
        models=ModelConfigs(
            master_mind=_model(agent.models.master_mind),
            slm=_model(agent.models.slm),
            video_generator=_model(agent.models.video_generator),
            image_generator=_model(agent.models.video_generator),
        ),
        skill=agent.skill,
        language=agent.language,
        brief=Brief(prompt=fill(agent.brief.prompt), mood=fill(agent.brief.mood)),
        avatar=agent.avatar,
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
