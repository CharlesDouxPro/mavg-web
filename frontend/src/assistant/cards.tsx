// Les cartes de l'assistant : ce qu'il propose, et le clic qui l'exécute côté serveur.

import { useEffect, useRef, useState, type ReactNode } from "react";
import { AvatarPicker, ReferencePicker, VoicePicker } from "../channels/Assets";
import { LANGUAGE_FR, SEX_LABEL, copy, flag, shortValue, slugify } from "../lib/format";
import { href } from "../lib/router";
import { Icon, type IconName } from "../ui/Icon";
import { Media, Notice } from "../ui/kit";
import { useToast } from "../ui/overlay";
import type { Card, CardAction, ChannelCard, ImageCard, RunsCard, VoiceView, VoicesCard } from "./api";

interface CardProps<C extends Card> {
  card: C;
  /** Un tour est en cours : aucun clic ne part. */
  busy: boolean;
  onAct: (action: CardAction) => void;
}

export function CardView({ card, busy, onAct }: CardProps<Card>) {
  if (card.kind === "image") return <ImageCardView card={card} busy={busy} onAct={onAct} />;
  if (card.kind === "voices") return <VoicesCardView card={card} busy={busy} onAct={onAct} />;
  if (card.kind === "channel") return <ChannelCardView card={card} busy={busy} onAct={onAct} />;
  return <RunsCardView card={card} busy={busy} onAct={onAct} />;
}

function Frame({
  icon,
  title,
  sub,
  card,
  children,
}: {
  icon: IconName;
  title: string;
  sub?: string;
  card: Card;
  children: ReactNode;
}) {
  return (
    <div className={`card chat-card${card.status === "open" ? " open" : ""}`}>
      <div className="card-head">
        <div className="card-icon">
          <Icon name={icon} />
        </div>
        <div className="grow">
          <h3 className="card-title">{title}</h3>
          {sub && <p className="card-sub">{sub}</p>}
        </div>
        <StatusChip card={card} />
      </div>
      <div className="card-body stack" style={{ gap: 12 }}>
        {children}
      </div>
    </div>
  );
}

function StatusChip({ card }: { card: Card }) {
  if (card.status === "open") return <span className="badge accent">À décider</span>;
  if (card.status === "done")
    return (
      <span className="badge done">
        <Icon name="check" size={11} />
        Fait
      </span>
    );
  if (card.status === "failed") return <span className="badge failed">Refusé</span>;
  return <span className="badge outline">Écartée</span>;
}

function Dismiss({ busy, onAct }: { busy: boolean; onAct: (action: CardAction) => void }) {
  return (
    <button type="button" className="btn ghost sm" disabled={busy} onClick={() => onAct({ action: "cancel" })}>
      Écarter
    </button>
  );
}

// --- Image ---

function ImageCardView({ card, busy, onAct }: CardProps<ImageCard>) {
  const [open, setOpen] = useState(false);
  const toast = useToast();
  const { purpose, name, prompt, why } = card.payload;
  const Picker = purpose === "avatar" ? AvatarPicker : ReferencePicker;
  return (
    <Frame
      icon={purpose === "avatar" ? "user" : "sparkles"}
      title={`${purpose === "avatar" ? "Avatar" : "Image de référence"} · ${name}`}
      sub={why}
      card={card}
    >
      <div>
        <div className="preview-head">
          <strong className="small">Prompt à donner à ton générateur d'images</strong>
          <button
            type="button"
            className="btn xs"
            style={{ marginLeft: "auto" }}
            onClick={async () => {
              if (await copy(prompt)) toast("ok", "Prompt copié");
              else toast("error", "Copie impossible", "Sélectionne le texte à la main.");
            }}
          >
            <Icon name="copy" size={12} />
            Copier
          </button>
        </div>
        <pre className="preview preview-box">{prompt}</pre>
      </div>
      {card.status === "open" && (
        <>
          <div className="row">
            <button type="button" className="btn primary sm" disabled={busy} onClick={() => setOpen(!open)}>
              <Icon name={open ? "x" : "upload"} size={13} />
              {open ? "Fermer" : "Déposer l'image"}
            </button>
            <span className="faint small grow">
              {purpose === "avatar" ? "PNG de préférence, ou une image déjà dans le bucket." : "PNG, JPEG ou WebP."}
            </span>
            <Dismiss busy={busy} onAct={onAct} />
          </div>
          {open && (
            <Picker
              value=""
              suggestedName={slugify(name)}
              onPick={(asset) => {
                setOpen(false);
                onAct({ action: "attach", uri: asset.uri });
              }}
            />
          )}
        </>
      )}
      {card.status === "done" && card.result.media && (
        <div className="row">
          <Media url={card.result.media.url} kind={card.result.media.kind} className="thumb m" />
          <span className="mono small truncate">{shortValue(card.result.media.uri)}</span>
        </div>
      )}
    </Frame>
  );
}

// --- Voix ---

function usePlayer() {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  useEffect(() => () => audio.current?.pause(), []);
  const toggle = (voice: VoiceView) => {
    audio.current?.pause();
    if (playing === voice.uri || !voice.url) return setPlaying(null);
    const element = new Audio(voice.url);
    element.onended = () => setPlaying(null);
    element.play().catch(() => setPlaying(null));
    audio.current = element;
    setPlaying(voice.uri);
  };
  return { playing, toggle };
}

function VoicesCardView({ card, busy, onAct }: CardProps<VoicesCard>) {
  const { playing, toggle } = usePlayer();
  const [all, setAll] = useState(false);
  const chosen = card.result.uri;
  const language = card.voices.find((voice) => voice.language)?.language ?? "";
  return (
    <Frame icon="mic" title="Voix proposées" sub={card.payload.why} card={card}>
      <div className="stack" style={{ gap: 8 }}>
        {card.voices.map((voice) => (
          <div key={voice.uri} className={`voice voice-pick${voice.uri === chosen ? " selected" : ""}`}>
            <button
              type="button"
              className={`play${playing === voice.uri ? " on" : ""}`}
              disabled={!voice.url}
              onClick={() => toggle(voice)}
              aria-label={`Écouter ${voice.name}`}
            >
              {playing === voice.uri ? (
                <span className="wave"><i /><i /><i /><i /></span>
              ) : (
                <Icon name="play" size={12} />
              )}
            </button>
            <span className="grow" style={{ minWidth: 0 }}>
              <div className="voice-name">{voice.name}</div>
              <div className="voice-meta">
                {voice.language && `${flag(voice.language)} ${SEX_LABEL[voice.sex ?? ""] ?? voice.sex} · ${voice.age_range}`}
                {voice.missing && "Absente du catalogue"}
              </div>
              {voice.description && <p className="small muted" style={{ margin: "4px 0 0" }}>{voice.description}</p>}
            </span>
            {card.status === "open" && !voice.missing && (
              <button type="button" className="btn sm" disabled={busy} onClick={() => onAct({ action: "choose", uri: voice.uri })}>
                Choisir
              </button>
            )}
            {voice.uri === chosen && <Icon name="check" size={14} />}
          </div>
        ))}
      </div>
      {card.status === "open" && (
        <>
          <div className="row">
            <button type="button" className="btn ghost sm" onClick={() => setAll(!all)}>
              {all ? "Masquer le catalogue" : `Voir toutes les voix${language ? ` en ${LANGUAGE_FR[language] ?? language}` : ""}`}
            </button>
            <span className="grow" />
            <Dismiss busy={busy} onAct={onAct} />
          </div>
          {all && <VoicePicker value="" language={language} onPick={(uri) => uri && onAct({ action: "choose", uri })} />}
        </>
      )}
    </Frame>
  );
}

// --- Channel ---

function ChannelCardView({ card, busy, onAct }: CardProps<ChannelCard>) {
  const { channel, base_version, advice } = card.payload;
  const agent = channel.agent_config;
  const plan = agent.plan as {
    arc?: string[];
    min_total_seconds?: number;
    max_total_seconds?: number;
    max_silent_shots?: number;
  };
  const saved = card.status === "done" ? card.result : null;
  return (
    <Frame
      icon="layers"
      title={`${base_version === null ? "Nouveau channel" : `Mise à jour (version ${base_version})`} · ${channel.name}`}
      sub={channel.description}
      card={card}
    >
      <div className="row" style={{ alignItems: "flex-start", gap: 14 }}>
        {card.avatar && <Media url={card.avatar.url} kind={card.avatar.kind} className="thumb portrait chat-portrait" />}
        <dl className="kv grow">
          <dt>Identifiant</dt>
          <dd className="mono">{channel.id}</dd>
          <dt>Langue</dt>
          <dd>{agent.language ? `${flag(agent.language)} ${LANGUAGE_FR[agent.language] ?? agent.language}` : "—"}</dd>
          <dt>Brief</dt>
          <dd>{agent.brief.prompt}</dd>
          {agent.brief.mood && (
            <>
              <dt>Mood</dt>
              <dd>{agent.brief.mood}</dd>
            </>
          )}
          <dt>Paramètres</dt>
          <dd>{channel.parameters.map((p) => `${p.name}${p.required ? "*" : ""} (${p.type})`).join(", ") || "aucun"}</dd>
          <dt>Format</dt>
          <dd>
            {(plan.arc ?? []).join(" → ")} · {plan.min_total_seconds}-{plan.max_total_seconds} s
            {plan.max_silent_shots ? ` · ${plan.max_silent_shots} plan${plan.max_silent_shots > 1 ? "s" : ""} muet${plan.max_silent_shots > 1 ? "s" : ""} au plus` : ""}
          </dd>
          <dt>Avatar</dt>
          <dd>
            {agent.avatar.name || "—"}
            {agent.avatar.appearance && <div className="muted small">{agent.avatar.appearance}</div>}
          </dd>
          <dt>Voix</dt>
          <dd>{card.voice ? card.voice.name : "aucune"}</dd>
          <dt>Publication</dt>
          <dd>
            {channel.channel_config.channel_name} · {channel.channel_config.email}
          </dd>
        </dl>
      </div>
      {card.status === "open" && advice.length > 0 && (
        <Notice tone="warn">
          {advice.map((line) => (
            <div key={line}>{line}</div>
          ))}
        </Notice>
      )}
      {card.status === "open" && (
        <div className="row">
          <button type="button" className="btn primary sm" disabled={busy} onClick={() => onAct({ action: "confirm" })}>
            <Icon name="save" size={13} />
            Enregistrer
          </button>
          <span className="grow" />
          <Dismiss busy={busy} onAct={onAct} />
        </div>
      )}
      {saved && (
        <div className="row">
          <span className="small">Enregistré · version {saved.version}</span>
          <a className="btn sm" href={href({ page: "channels", id: saved.channel_id })} style={{ marginLeft: "auto" }}>
            <Icon name="external" size={13} />
            Ouvrir dans l'éditeur
          </a>
        </div>
      )}
      {saved?.warnings?.length ? <Notice tone="warn">{saved.warnings.join(" ")}</Notice> : null}
      {card.status === "failed" && card.error && <Notice tone="error">{card.error}</Notice>}
    </Frame>
  );
}

// --- Runs ---

function RunsCardView({ card, busy, onAct }: CardProps<RunsCard>) {
  const { candidates, channel_name, channel_version } = card.payload;
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const results = new Map((card.result.runs ?? []).map((result) => [result.n, result]));
  const open = card.status === "open";
  const toggle = (n: number) =>
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(n)) next.delete(n);
      else next.add(n);
      return next;
    });
  const added = [...results.values()].filter((result) => result.task_id).length;

  return (
    <Frame
      icon="rocket"
      title={`${candidates.length} runs proposés · ${channel_name}`}
      sub={open ? "Coche ceux qui partent dans la file du worker." : `${added} ajouté(s) à la file.`}
      card={card}
    >
      <div className="run-list">
        {candidates.map((candidate) => {
          const result = results.get(candidate.n);
          return (
            <label
              key={candidate.n}
              className={`run-row${checked.has(candidate.n) ? " checked" : ""}${open ? "" : " readonly"}`}
            >
              {open ? (
                <input type="checkbox" checked={checked.has(candidate.n)} disabled={busy} onChange={() => toggle(candidate.n)} />
              ) : (
                <span className="run-mark">{result?.task_id ? <Icon name="check" size={13} /> : result?.error ? <Icon name="alert" size={13} /> : null}</span>
              )}
              <span className="faint small mono">{candidate.n}</span>
              <span style={{ minWidth: 0 }}>
                <div className="run-pitch">{candidate.pitch}</div>
                <div className="small muted">
                  {Object.entries(candidate.values)
                    .map(([name, value]) => `${name} : ${shortValue(value)}`)
                    .join(" · ")}
                </div>
                {result?.task_id && (
                  <a className="small mono" href={href({ page: "runs", id: result.task_id })}>
                    {result.task_id} · position {result.queue_position}
                  </a>
                )}
                {result?.error && <div className="small" style={{ color: "var(--danger)" }}>{result.error}</div>}
              </span>
            </label>
          );
        })}
      </div>
      {open && (
        <div className="row">
          <button type="button" className="btn primary sm" disabled={busy || checked.size === 0} onClick={() => onAct({ action: "confirm", selected: [...checked].sort((a, b) => a - b) })}>
            <Icon name="rocket" size={13} />
            {checked.size ? `Ajouter ${checked.size} run${checked.size > 1 ? "s" : ""} à la file` : "Coche des runs"}
          </button>
          <button
            type="button"
            className="btn ghost sm"
            disabled={busy}
            onClick={() => setChecked(checked.size === candidates.length ? new Set() : new Set(candidates.map((c) => c.n)))}
          >
            {checked.size === candidates.length ? "Tout décocher" : "Tout cocher"}
          </button>
          <span className="faint small grow" style={{ textAlign: "right" }}>
            channel v{channel_version}
          </span>
          <Dismiss busy={busy} onAct={onAct} />
        </div>
      )}
    </Frame>
  );
}
