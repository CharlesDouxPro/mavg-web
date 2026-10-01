// L'onglet Assistant : discuter pour créer un channel, puis y proposer des runs.

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ApiError } from "../api";
import { PromptPreview } from "../channels/PromptPreview";
import { LANGUAGE_FR, ago, flag } from "../lib/format";
import { go, href } from "../lib/router";
import { useStudio } from "../studio";
import { Icon, Spinner } from "../ui/Icon";
import { Empty, Media, Notice } from "../ui/kit";
import { assistantApi, type CardAction, type Conversation, type ConversationSummary } from "./api";
import { CardView } from "./cards";
import "./assistant.css";

const message = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

const STARTERS = [
  "Je veux une chaîne sur un hérisson boulanger qui raconte sa journée.",
  "Aide-moi à trouver un personnage récurrent pour une chaîne de micro-fictions.",
  "Propose-moi 10 runs pour un de mes channels.",
];

export function AssistantPage({ selected }: { selected?: string }) {
  return selected ? <ConversationView key={selected} id={selected} /> : <Home />;
}

function Home() {
  const { channels } = useStudio();
  const [list, setList] = useState<ConversationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [channelId, setChannelId] = useState("");

  useEffect(() => {
    assistantApi
      .list()
      .then(setList)
      .catch((err) => setError(message(err)));
  }, []);

  const start = async (channel?: string) => {
    setStarting(true);
    try {
      const conversation = await assistantApi.start(channel);
      go({ page: "assistant", id: conversation.id });
    } catch (err) {
      setError(message(err));
      setStarting(false);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Assistant</h1>
          <p className="page-sub">
            Raconte ton idée : il pose les questions, prépare le channel et propose des runs. Rien ne s'enregistre sans
            ton clic.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn primary" disabled={starting} onClick={() => start()}>
            <Icon name="sparkles" />
            Nouveau channel
          </button>
        </div>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="assistant-home">
        <div className="card">
          <div className="card-head">
            <div className="card-icon">
              <Icon name="rocket" />
            </div>
            <div className="grow">
              <h3 className="card-title">Partir d'un channel existant</h3>
              <p className="card-sub">Pour proposer des runs, ou le retoucher.</p>
            </div>
          </div>
          <div className="card-body row">
            <select className="input grow" value={channelId} onChange={(e) => setChannelId(e.target.value)}>
              <option value="">Choisir un channel…</option>
              {channels?.map((channel) => (
                <option key={channel.id} value={channel.id}>
                  {channel.name}
                </option>
              ))}
            </select>
            <button className="btn" disabled={!channelId || starting} onClick={() => start(channelId)}>
              Ouvrir
            </button>
          </div>
        </div>
        <div className="card">
          <div className="card-head">
            <div className="card-icon">
              <Icon name="clock" />
            </div>
            <div className="grow">
              <h3 className="card-title">Conversations récentes</h3>
            </div>
          </div>
          <div className="card-body stack" style={{ gap: 6 }}>
            {!list && !error && <div className="skeleton" style={{ height: 80 }} />}
            {list?.length === 0 && <p className="muted small">Aucune conversation pour l'instant.</p>}
            {list?.map((item) => (
              <a key={item.id} className="assistant-session" href={href({ page: "assistant", id: item.id })}>
                <span className="grow truncate">{item.title}</span>
                {item.channel_name && <span className="badge outline">{item.channel_name}</span>}
                <span className="faint small">{ago(item.updated_at)}</span>
              </a>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function ConversationView({ id }: { id: string }) {
  const { reloadChannels, refreshQueue } = useStudio();
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const log = useRef<HTMLDivElement>(null);

  const reload = useCallback(
    () =>
      assistantApi
        .get(id)
        .then(setConversation)
        .catch((err) => setLoadError(message(err))),
    [id],
  );
  useEffect(() => {
    reload();
  }, [reload]);

  // Une autre fenêtre fait répondre l'assistant : on suit jusqu'à la fin de son tour.
  useEffect(() => {
    if (!conversation?.busy || working) return;
    const timer = setTimeout(reload, 3000);
    return () => clearTimeout(timer);
  }, [conversation, working, reload]);

  useLayoutEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" });
  }, [conversation?.items.length, pending, working, error]);

  /** Un tour : la réponse remplace la conversation ; en cas d'échec, on relit ce que le serveur a gardé. */
  const turn = async (call: () => Promise<Conversation>, after?: () => void) => {
    setWorking(true);
    setError(null);
    try {
      setConversation(await call());
    } catch (err) {
      setError(message(err));
      await reload();
    } finally {
      setWorking(false);
      setPending(null);
      after?.();
    }
  };

  const send = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed || working) return;
    setText("");
    setPending(trimmed);
    turn(() => assistantApi.send(id, trimmed));
  };

  const act = (cardId: string, kind: string, action: CardAction) =>
    turn(
      () => assistantApi.act(id, cardId, action),
      () => {
        // Le reste du Studio ne se met à jour que toutes les 30 s : on le prévient tout de suite.
        if (kind === "channel" || kind === "runs") reloadChannels();
        if (kind === "runs") refreshQueue();
      },
    );

  if (loadError)
    return (
      <Empty icon="alert" title="Conversation introuvable">
        <p>{loadError}</p>
        <a className="btn" href={href({ page: "assistant" })}>
          Toutes les conversations
        </a>
      </Empty>
    );
  if (!conversation) return <div className="skeleton" style={{ height: 420 }} />;

  const busy = working || conversation.busy;
  const last = conversation.items[conversation.items.length - 1];
  const unanswered = !busy && last !== undefined && (last.kind === "user" || last.kind === "note");

  return (
    <div className="assistant-page">
      <section className="chat">
        <header className="chat-head">
          <a className="btn ghost sm icon" href={href({ page: "assistant" })} aria-label="Toutes les conversations">
            <Icon name="chevron" className="flip" />
          </a>
          <strong className="grow truncate">{conversation.title || "Nouvelle conversation"}</strong>
        </header>

        <div className="chat-log" ref={log}>
          {conversation.items.length === 0 && !pending && (
            <div className="chat-welcome">
              <div className="empty-icon">
                <Icon name="sparkles" size={22} />
              </div>
              <p className="muted">
                Dis-moi ce que tu as en tête, même flou : on trouvera le personnage, le ton et le format ensemble.
              </p>
              <div className="stack" style={{ gap: 8 }}>
                {STARTERS.map((starter) => (
                  <button key={starter} type="button" className="btn starter" onClick={() => send(starter)}>
                    {starter}
                  </button>
                ))}
              </div>
            </div>
          )}
          {conversation.items.map((item, index) => {
            if (item.kind === "card")
              return (
                <CardView
                  key={item.card.id}
                  card={item.card}
                  busy={busy}
                  onAct={(action) => act(item.card.id, item.card.kind, action)}
                />
              );
            if (item.kind === "note")
              return (
                <div key={index} className="chat-note">
                  <Icon name="info" size={13} />
                  <span>{item.text}</span>
                </div>
              );
            return (
              <div key={index} className={`bubble ${item.kind}`}>
                {item.text}
              </div>
            );
          })}
          {pending && <div className="bubble user">{pending}</div>}
          {busy && (
            <div className="bubble assistant thinking">
              <Spinner size={13} />
              L'assistant réfléchit…
            </div>
          )}
          {error && (
            <Notice tone="error">
              <div className="row wrap">
                <span className="grow">{error}</span>
                {unanswered && (
                  <button type="button" className="btn sm" onClick={() => turn(() => assistantApi.send(id, ""))}>
                    <Icon name="refresh" size={13} />
                    Réessayer
                  </button>
                )}
              </div>
            </Notice>
          )}
        </div>

        <form
          className="chat-compose"
          onSubmit={(e) => {
            e.preventDefault();
            send(text);
          }}
        >
          <textarea
            className="input"
            rows={2}
            value={text}
            disabled={busy}
            placeholder="Ton idée, ta réponse… Entrée pour envoyer, Maj+Entrée pour aller à la ligne."
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                send(text);
              }
            }}
          />
          <button className="btn primary icon" type="submit" disabled={busy || !text.trim()} aria-label="Envoyer">
            <Icon name="send" />
          </button>
        </form>
      </section>

      <DraftPanel conversation={conversation} />
    </div>
  );
}

function DraftPanel({ conversation }: { conversation: Conversation }) {
  const { draft, draft_media, base_version, references } = conversation;
  if (!draft)
    return (
      <aside className="draft-panel">
        <div className="card">
          <Empty icon="layers" title="Pas encore de channel">
            <p>Le brouillon se remplit au fil de la conversation.</p>
          </Empty>
        </div>
      </aside>
    );
  const agent = draft.agent_config;
  return (
    <aside className="draft-panel stack">
      <div className="card">
        <div className="card-head">
          <div className="grow" style={{ minWidth: 0 }}>
            <h3 className="card-title truncate">{draft.name || "Channel sans nom"}</h3>
            <p className="card-sub mono truncate">{draft.id || "sans identifiant"}</p>
          </div>
          {base_version !== null ? (
            <span className="badge done">v{base_version}</span>
          ) : (
            <span className="badge outline">brouillon</span>
          )}
        </div>
        <div className="card-body stack" style={{ gap: 12 }}>
          <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
            <Media url={draft_media.avatar?.url} kind={draft_media.avatar?.kind ?? "image"} className="thumb portrait draft-portrait" />
            <dl className="kv grow">
              <dt>Avatar</dt>
              <dd>{agent.avatar.name || "—"}</dd>
              <dt>Voix</dt>
              <dd style={{ textTransform: "capitalize" }}>{draft_media.voice?.name ?? "—"}</dd>
              <dt>Langue</dt>
              <dd>{agent.language ? `${flag(agent.language)} ${LANGUAGE_FR[agent.language] ?? agent.language}` : "—"}</dd>
              <dt>Runs</dt>
              <dd>{draft.parameters.map((parameter) => parameter.name).join(", ") || "—"}</dd>
            </dl>
          </div>
          {agent.avatar.appearance && <p className="small muted" style={{ margin: 0 }}>{agent.avatar.appearance}</p>}
          {references.length > 0 && (
            <div className="stack" style={{ gap: 6 }}>
              <strong className="small">Images de référence</strong>
              {references.map((reference) => (
                <div key={reference.uri} className="row small" title={reference.uri}>
                  <Media url={reference.url} kind="image" />
                  {reference.name}
                </div>
              ))}
            </div>
          )}
          {base_version !== null && (
            <a className="btn sm" href={href({ page: "channels", id: draft.id })}>
              <Icon name="external" size={13} />
              Ouvrir dans l'éditeur
            </a>
          )}
        </div>
      </div>
      {agent.brief.prompt && (
        <div className="card">
          <div className="card-body">
            <PromptPreview channel={draft} compact />
          </div>
        </div>
      )}
    </aside>
  );
}
