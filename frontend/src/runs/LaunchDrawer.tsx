// Lancer un run : choisir le channel, remplir ses paramètres, voir le prompt final, lancer.

import { useEffect, useState } from "react";
import { ApiError, api, type Channel, type Issue } from "../api";
import { toData } from "../channels/ChannelEditor";
import { ParameterValueInput } from "../channels/Parameters";
import { PromptPreview } from "../channels/PromptPreview";
import { LANGUAGE_FR, flag } from "../lib/format";
import { go } from "../lib/router";
import { useStudio, type LaunchRequest } from "../studio";
import { Icon, Spinner } from "../ui/Icon";
import { Empty, Field, Media, Notice, issueFor } from "../ui/kit";
import { Drawer, useToast } from "../ui/overlay";

const LAST_CHANNEL = "mavg.last-channel";
const remember = {
  get: () => {
    try {
      return localStorage.getItem(LAST_CHANNEL);
    } catch {
      return null;
    }
  },
  set: (id: string) => {
    try {
      localStorage.setItem(LAST_CHANNEL, id);
    } catch {
      /* rien : ce n'est qu'une préférence */
    }
  },
};

export function LaunchDrawer({
  request,
  onClose,
  onLaunched,
}: {
  request: LaunchRequest | null;
  onClose: () => void;
  onLaunched: () => void;
}) {
  const { channels } = useStudio();
  const toast = useToast();
  const [channelId, setChannelId] = useState<string | null>(null);
  const [channel, setChannel] = useState<Channel | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [issues, setIssues] = useState<Issue[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // À l'ouverture : le channel demandé, sinon le dernier utilisé, sinon le premier.
  useEffect(() => {
    if (!request) return;
    const remembered = remember.get();
    const known = (id: string | null | undefined) => (id && channels?.some((c) => c.id === id) ? id : null);
    setChannelId(known(request.channelId) ?? known(remembered) ?? channels?.[0]?.id ?? null);
    setIssues([]);
    setProblem(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request]);

  // Le channel est rechargé à chaque ouverture : le formulaire part de sa dernière version.
  useEffect(() => {
    if (!request || !channelId) return setChannel(null);
    let cancelled = false;
    setChannel(null);
    api
      .channel(channelId)
      .then(({ channel }) => {
        if (cancelled) return;
        setChannel(channel);
        const defaults = Object.fromEntries(channel.parameters.map((p) => [p.name, p.default]));
        const reused = request.channelId === channelId ? request.values ?? {} : {};
        setValues({ ...defaults, ...Object.fromEntries(Object.entries(reused).filter(([name]) => name in defaults)) });
      })
      .catch((err) => !cancelled && setProblem(err instanceof ApiError ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [request, channelId]);

  const launch = async () => {
    if (!channel) return;
    setBusy(true);
    setIssues([]);
    setProblem(null);
    try {
      const result = await api.launch(channel.id, values, channel.version);
      remember.set(channel.id);
      toast("ok", "Run lancé", `${result.queue_position === 1 ? "Prochain servi" : `${result.queue_position}ᵉ dans la file`} · ${channel.name}`);
      onLaunched();
      onClose();
      go({ page: "runs", id: result.task_id });
    } catch (err) {
      if (err instanceof ApiError && err.issues.length) {
        setIssues(err.issues);
        const general = err.issues.filter((issue) => !issue.key.startsWith("values."));
        if (general.length) setProblem(general.map((issue) => issue.message).join(" "));
      } else {
        setProblem(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy(false);
    }
  };

  const summary = channels?.find((item) => item.id === channelId);
  const agent = channel?.agent_config;

  return (
    <Drawer
      open={request !== null}
      onClose={onClose}
      wide
      title="Nouveau run"
      subtitle="Les paramètres remplacent les ${…} du brief ; le run part dans la file du worker."
      footer={
        <>
          <span className="muted small grow">
            {channel && `Channel « ${channel.name} », version ${channel.version}.`}
          </span>
          <button className="btn ghost" onClick={onClose}>
            Annuler
          </button>
          <button className="btn primary" onClick={launch} disabled={!channel || busy}>
            {busy ? <Spinner /> : <Icon name="rocket" />}
            Lancer le run
          </button>
        </>
      }
    >
      {channels?.length === 0 && (
        <Empty icon="layers" title="Aucun channel">
          <p>Crée d'abord un channel : c'est lui qui porte le brief, l'avatar et les paramètres.</p>
          <a className="btn" href="#/channels/new" onClick={onClose}>
            <Icon name="plus" /> Nouveau channel
          </a>
        </Empty>
      )}

      {channels && channels.length > 0 && (
        <div>
          <h4 className="section-title">Channel</h4>
          <div className="channel-pick">
            {channels.map((item) => (
              <button key={item.id} type="button" className={item.id === channelId ? "on" : undefined} onClick={() => setChannelId(item.id)}>
                <Media url={item.avatar?.url} kind={item.avatar?.kind ?? "image"} />
                <span style={{ minWidth: 0 }}>
                  <div className="truncate" style={{ fontWeight: 600 }}>{item.name}</div>
                  <div className="muted small truncate">
                    {item.language && `${flag(item.language)} `}
                    {item.parameters.length ? item.parameters.map((name) => `\${${name}}`).join(" ") : "sans paramètre"}
                  </div>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {problem && <Notice tone="error">{problem}</Notice>}
      {channelId && !channel && !problem && (
        <div className="empty">
          <Spinner size={20} />
        </div>
      )}

      {channel && agent && (
        <div className="launch-grid">
          <div className="stack">
            <h4 className="section-title" style={{ margin: 0 }}>Paramètres</h4>
            {channel.parameters.length === 0 && (
              <Notice tone="info">
                Ce channel n'a pas de paramètre : le run reprend son brief tel quel.
              </Notice>
            )}
            {channel.parameters.map((parameter) => (
              <Field
                key={parameter.name}
                label={<code>{parameter.name}</code>}
                required={parameter.required}
                help={parameter.description || undefined}
                error={issueFor(issues, `values.${parameter.name}`)}
              >
                <ParameterValueInput
                  type={parameter.type}
                  value={values[parameter.name] ?? ""}
                  placeholder={parameter.default || undefined}
                  onChange={(next) => {
                    setValues((current) => ({ ...current, [parameter.name]: next }));
                    setIssues((current) => current.filter((issue) => issue.key !== `values.${parameter.name}`));
                  }}
                />
              </Field>
            ))}

            <div className="card card-body" style={{ padding: 14 }}>
              <div className="row" style={{ gap: 12 }}>
                <Media url={summary?.avatar?.url} kind={summary?.avatar?.kind ?? "image"} className="thumb m" />
                <dl className="kv grow" style={{ margin: 0 }}>
                  <dt>Avatar</dt>
                  <dd>{agent.avatar.name || "—"}</dd>
                  <dt>Voix</dt>
                  <dd>{agent.avatar.voice_url ? agent.avatar.voice_url.split("/").pop()?.replace(".wav", "") : "inventée par le modèle"}</dd>
                  <dt>Langue</dt>
                  <dd>{agent.language ? `${flag(agent.language)} ${LANGUAGE_FR[agent.language] ?? agent.language}` : "libre"}</dd>
                  <dt>Livraison</dt>
                  <dd>{channel.channel_config.email}</dd>
                </dl>
              </div>
            </div>
          </div>
          <div>
            <PromptPreview channel={toData(channel)} values={values} />
          </div>
        </div>
      )}
    </Drawer>
  );
}
