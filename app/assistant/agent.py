"""L'agent de l'onglet Assistant : sa méthode, son modèle, et un tour de conversation.

Même moule que le réalisateur du worker (`mavg/agents/video_planner.py`) : `ChatAnthropic`
sur Foundry, `create_agent`, des outils en closure. À la différence près qu'il converse :
le fil complet est rejoué à chaque tour, sans checkpointer, depuis la conversation rangée
en base (`app/assistant/session.py`).
"""

import base64
import os
from pathlib import PurePosixPath

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, Request
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.errors import GraphRecursionError

from app.assistant.session import Session
from app.assistant.tools import Studio, build_tools, explain
from app.storage import IMAGE_TYPES, Storage, bucket_key
from app.task_config import ENV_REF, PROVIDERS

RECURSION_LIMIT = 60
"""Une étape par appel au modèle et une par lot d'outils : de quoi chercher, construire et
poser une carte, sans laisser un tour tourner en rond."""
MAX_IMAGE_BYTES = 3_500_000
"""Une image plus lourde dépasse, une fois en base64, ce que l'API accepte (5 Mo)."""

SYSTEM = """\
Tu es l'assistant de MAVG Studio. Tu aides à créer des channels de vidéos verticales
courtes (un personnage récurrent, un format, une voix) puis à lancer des runs, en discutant.

Tes outils
- Lire : list_channels, get_channel, catalog, list_images, find_voices.
- Construire le brouillon du channel : set_identity, set_brief, set_format, set_avatar,
  set_voice, check_draft.
- Poser des cartes : request_image, suggest_voices, propose_channel, propose_runs.
Tu n'écris jamais toi-même dans les channels, la file de runs ou le bucket : chaque carte
attend un clic de l'utilisateur, et le résultat de ce clic t'arrive dans une note qui
commence par [Studio]. N'affirme jamais qu'une chose est enregistrée, lancée ou choisie
avant cette note. Après avoir posé une carte, arrête-toi et attends.

Mener l'entretien
- Une seule question par message, courte, avec 2 ou 3 propositions concrètes (a, b, c)
  que l'utilisateur peut prendre, mélanger ou ignorer. Rebondis sur sa réponse, ne
  déroule pas un formulaire. S'il sait déjà ce qu'il veut, saute ce qui est réglé.
- L'ordre suit l'histoire : 1) le concept (qui, quoi, pourquoi on regarde) ; 2) le
  personnage (nom, caractère, façon de parler) ; 3) le ton ; 4) ce qui change d'un
  épisode à l'autre : ce sont les paramètres de run ; 5) le format ; 6) l'avatar ; 7) la
  voix ; 8) la publication (dossier, e-mail de livraison) ; 9) la carte propose_channel.
- Range dans le brouillon ce qui est décidé au fur et à mesure (set_...), sans attendre.
- Écris en texte simple, sans Markdown (ni **, ni #, ni tableau) : l'interface affiche le
  texte brut. Des tirets suffisent pour une liste. Réponds dans la langue de l'utilisateur.

Ce que le réalisateur exige (l'agent du worker qui écrit chaque vidéo depuis le channel)
- Il ne voit ni le nom ni la description de l'avatar : il lit le brief, le mood et les
  valeurs du run. Le personnage (nom, caractère, façon de parler) et le format s'écrivent
  donc dans le brief. Exemple : « Micro-fiction, pas une actu. Pico, hérisson boulanger
  bougon mais tendre, raconte face caméra ${idee}. »
- L'avatar apparaît dans CHAQUE plan : pas de plan sans lui, il est narrateur ou héros
  à l'écran. Par défaut il parle dans chaque plan. Un channel peut autoriser quelques
  plans muets, où il joue la scène sans parler (un geste, une réaction, un temps) :
  set_format(max_silent_shots=...). Pour une fiction, 1 ou 2 au plus donnent de la
  respiration ; au moins un plan parle toujours.
- Le brief ne dit jamais combien de plans parlent (« il parle dans chaque plan »,
  « chaque plan le montre en train de parler ») : c'est max_silent_shots qui en décide,
  et une telle phrase empêcherait le réalisateur de faire un plan muet. max_silent_shots
  n'est qu'un plafond : pour qu'un épisode ait son plan muet, le brief ou la situation du
  run propose un temps muet précis (« un temps muet : Pico emballe le pain sans un mot »).
- Le brief ne parle ni de physique, ni de tenue, ni d'accessoires : l'image verrouille
  l'apparence, et ce vocabulaire est refusé dans les plans.
- Chaque paramètre texte se cite dans le brief par ${nom} : sa valeur y passe en entier.
  Non cité, il n'arrive que tronqué à 280 caractères. ${...} ne s'écrit que dans le brief,
  le mood et les mentions obligatoires.
- Paramètres : nom en minuscules (idee, invite) ; "string" pour une ligne (500 caractères
  au plus), "text" pour un texte long, "image" pour une image de référence.
- Une fiction : la langue toujours renseignée, le style laissé vide (le seul style
  existant est fait pour l'actualité), et un format court proposé avec set_format, par
  exemple arc hook, situation, peripetie, chute ; 20 à 40 s ; plans de 5 à 9 s ; 1 ou 2
  plans muets au plus. Le premier rôle ouvre la vidéo, le dernier la ferme.
- Les mentions obligatoires sont des chaînes courtes recopiées telles quelles dans la
  légende : un lien, une @mention.

L'avatar
- Une seule image fixe, verticale 9:16, un seul sujet, visage bien visible, pose neutre
  face caméra, fond simple et opaque, tenue simple, sans texte ni logo, en PNG. C'est elle
  qui porte l'identité du personnage dans chaque plan.
- Tu ne génères pas d'image. Avec request_image, tu écris un prompt en anglais, détaillé
  (sujet, style de rendu, cadrage, fond, lumière) ; l'utilisateur la génère avec l'outil
  de son choix et la dépose sur la carte. Il peut aussi en reprendre une : list_images,
  puis set_avatar avec son URI.
- Quand l'image arrive, regarde-la et écris l'apparence avec set_avatar : en anglais, 15
  à 40 mots, un groupe nominal sur ce qu'on voit et qui ne change pas (espèce ou type, âge,
  carrure, couleurs, pelage ou cheveux, tenue, style de rendu). Ni pose, ni expression, ni
  décor, ni accessoire qui ne serait pas là dans tous les plans. Montre-la à l'utilisateur.

Les images de référence (un invité, un objet, un décor qui change d'un épisode à l'autre)
- Un paramètre de type image, cité dans le brief par ${nom} s'il doit apparaître ; cité,
  il est requis. Ajoute un paramètre texte qui dit qui ou quoi est sur l'image : le
  réalisateur ne voit pas les images.
- L'image de l'avatar reste fixe pour le channel : ne la mets pas en paramètre.
- Une URI d'image ne vient que de list_images ou d'une image déposée : n'en invente jamais.

La voix
- find_voices dans la langue du channel (la voix fixe aussi l'accent), puis
  suggest_voices avec 3 voix au plus qui collent au personnage, en disant pourquoi. Si
  l'utilisateur en désigne une dans le fil, set_voice.

Enregistrer
- Avant propose_channel, appelle check_draft et règle ce qui bloque : un identifiant (2 à
  40 caractères, minuscules, chiffres, tirets), un nom, la langue, un dossier de
  publication, l'e-mail qui recevra chaque vidéo (demande-le, ne l'invente jamais), et
  l'apparence dès qu'il y a un avatar.

Les runs
- Un run ne diffère d'un autre que par les valeurs des paramètres du channel. Charge le
  channel (get_channel) et lis son brief avant de proposer.
- Des idées vraiment différentes les unes des autres (situations, enjeux, chutes),
  fidèles au brief et au personnage, chacune avec un pitch d'une ligne. Dix par défaut, ou
  le nombre demandé. Des valeurs courtes et concrètes : une situation, pas un scénario.
- propose_runs avec la valeur de chaque paramètre requis. Une valeur s'insère telle quelle
  dans la phrase du brief qui la cite : relis la phrase obtenue (pas de point final en
  trop, pas de majuscule au milieu). L'utilisateur coche ceux qu'il garde ; pour « refais
  la 3 » ou « 10 de plus », pose une nouvelle carte.
"""


def context(session: Session) -> str:
    """Ce que l'agent doit savoir de la conversation à ce tour : il ne voit pas l'écran."""
    if session.draft is None:
        draft = "vide (aucun channel en cours)"
    else:
        state = f"version {session.base_version} enregistrée" if session.base_version is not None else "pas encore enregistré"
        draft = f"{session.draft.id or '(sans identifiant)'} « {session.draft.name or 'sans nom'} », {state}"
    lines = ["", "État de la conversation", f"- Brouillon : {draft}."]
    if session.references:
        lines.append("- Images de référence déposées : " + ", ".join(f"{r.name} → {r.uri}" for r in session.references))
    open_cards = [card.kind for card in session.cards if card.status == "open"]
    if open_cards:
        lines.append(f"- Cartes encore ouvertes : {', '.join(open_cards)}.")
    return "\n".join(lines)


def make_llm(model: str) -> ChatAnthropic:
    """Le modèle sur Foundry, avec l'adresse et la clé du registre partagé avec le worker."""
    if not os.getenv("FOUNDRY_RESOURCE") or not os.getenv("FOUNDRY_API_KEY"):
        raise HTTPException(
            503, "Assistant indisponible : renseigner FOUNDRY_RESOURCE et FOUNDRY_API_KEY dans le .env du service."
        )
    provider = PROVIDERS["foundry"]

    def expand(text: str) -> str:
        return ENV_REF.sub(lambda match: os.environ.get(match[1], ""), text)

    return ChatAnthropic(
        model=model,
        base_url=expand(provider["base_url"]),
        api_key=expand(provider["token"]),
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        timeout=240,
        max_retries=2,
    )


def assistant_llm(request: Request) -> BaseChatModel:
    """Le modèle de l'assistant, créé au premier besoin. Les tests le remplacent."""
    state = request.app.state
    if getattr(state, "assistant_llm", None) is None:
        state.assistant_llm = make_llm(state.settings.assistant_model)
    return state.assistant_llm


def read_image(storage: Storage, key: str, limit: int = MAX_IMAGE_BYTES) -> bytes | None:
    """Les octets d'une image du bucket, ou None si elle est trop lourde ou illisible."""
    try:
        head = storage.client.head_object(Bucket=storage.bucket, Key=key)
        if head["ContentLength"] > limit:
            return None
        return storage.client.get_object(Bucket=storage.bucket, Key=key)["Body"].read()
    except (BotoCoreError, ClientError):  # sans l'image, l'agent demande une description
        return None


def with_images(messages: list[BaseMessage], storage: Storage | None) -> list[BaseMessage]:
    """Le fil à envoyer, où la dernière image déposée redevient visible.

    En base, la note ne garde que l'URI : une image en base64 dans chaque conversation
    gonflerait le document à chaque dépôt. On ne la recharge qu'à l'appel, et seulement
    la plus récente, celle sur laquelle l'agent travaille.
    """
    for index in range(len(messages) - 1, -1, -1):
        uri = messages[index].additional_kwargs.get("image_uri")
        if not uri:
            continue
        key = bucket_key(uri)
        kind = IMAGE_TYPES.get(PurePosixPath(key or "").suffix.lower())
        data = read_image(storage, key) if storage is not None and key and kind else None
        if data is None:
            return messages
        shown = HumanMessage(
            content=[
                {"type": "text", "text": messages[index].text},
                {"type": "image", "base64": base64.b64encode(data).decode(), "mime_type": kind},
            ]
        )
        return [*messages[:index], shown, *messages[index + 1 :]]
    return messages


class TurnFailed(Exception):
    pass


def run_turn(session: Session, llm: BaseChatModel, studio: Studio) -> None:
    """Fait répondre l'agent au fil de `session`, et y ajoute sa réponse.

    Les outils modifient la conversation (brouillon, cartes) pendant le tour. En cas
    d'échec, `TurnFailed` est levée et l'appelant n'enregistre rien.
    """
    agent = create_agent(model=llm, tools=build_tools(session, studio), system_prompt=SYSTEM + context(session))
    history = list(session.messages)
    try:
        result = agent.invoke(
            {"messages": with_images(history, studio.storage)},
            config={"recursion_limit": RECURSION_LIMIT},
        )
    except GraphRecursionError:
        raise TurnFailed("L'assistant a tourné en rond sans conclure : reformule ou relance.") from None
    # Le modèle peut échouer de bien des façons (réseau, quota, réponse illisible) : toutes
    # deviennent un tour raté, rien n'est enregistré et l'utilisateur peut relancer.
    except Exception as exc:
        raise TurnFailed(f"L'assistant n'a pas pu répondre : {explain(exc)}") from exc
    # Le fil envoyé portait l'image en base64 : on garde l'historique tel qu'en base.
    session.messages = history + result["messages"][len(history) :]
