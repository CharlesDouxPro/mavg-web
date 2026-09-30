// La page Runs : la file et l'historique, filtrables, et le détail d'un run.

import { useState, type ReactNode } from "react";
import { api, type RunDetail, type RunSummary, type Status } from "../api";
import { usePolling } from "../lib/hooks";
import { STATUS_LABEL, ago, copy, duration, fullDate } from "../lib/format";
import { go } from "../lib/router";
import { useStudio } from "../studio";
import { Icon, Spinner, type IconName } from "../ui/Icon";
import { Empty, Notice, Segmented, StatusBadge, Steps, stageLabel } from "../ui/kit";
import { Drawer, useToast } from "../ui/overlay";

type Filter = "all" | Status;
const LIVE = (runs: { status: Status }[] | null) => runs?.some((run) => run.status === "pending" || run.status === "working");

export function RunsPage({ selected }: { selected?: string }) {
  const { channels, queue, runsVersion, launch } = useStudio();
  const [channelId, setChannelId] = useState("");
  const [status, setStatus] = useState<Filter>("all");
  const runs = usePolling(
    () => api.runs({ channel_id: channelId, status: status === "all" ? "" : status, limit: 100 }),
    [channelId, status, runsVersion],
    (data) => (LIVE(data) ? 3000 : 20_000),
  );

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Runs</h1>
          <p className="page-sub">La file du worker, dans l'ordre où il la traite, et tout ce qui a déjà tourné.</p>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={runs.refresh}>
            <Icon name="refresh" />
            Actualiser
          </button>
          <button className="btn primary" onClick={() => launch({ channelId: channelId || undefined })}>
            <Icon name="rocket" />
            Nouveau run
          </button>
        </div>
      </header>

      {queue && queue.pending > 0 && queue.working === 0 && (
        <div style={{ marginBottom: 16 }}>
          <Notice tone="info">
            <strong>{queue.pending} run{queue.pending > 1 ? "s" : ""} en attente, aucun en cours.</strong> Ils partiront dès que
            le worker tourne : démarre l'instance GPU (<code>docker compose … up --exit-code-from agent</code>).
          </Notice>
        </div>
      )}

      <div className="filters">
        <Segmented<Filter>
          value={status}
          onChange={setStatus}
          options={[
            { value: "all", label: "Tous" },
            { value: "pending", label: STATUS_LABEL.pending },
            { value: "working", label: STATUS_LABEL.working },
            { value: "done", label: "Terminés" },
            { value: "failed", label: "Échecs" },
          ]}
        />
        <select className="input" style={{ width: 240 }} value={channelId} onChange={(e) => setChannelId(e.target.value)}>
          <option value="">Tous les channels</option>
          {channels?.map((channel) => (
            <option key={channel.id} value={channel.id}>
              {channel.name}
            </option>
          ))}
        </select>
        {runs.data && <span className="faint small">{runs.data.length} run{runs.data.length > 1 ? "s" : ""}</span>}
      </div>

      {runs.error && <Notice tone="error">{runs.error.message}</Notice>}
      {!runs.data && !runs.error && (
        <div className="run-list">
          {Array.from({ length: 5 }, (_, i) => <div key={i} className="skeleton" style={{ height: 74 }} />)}
        </div>
      )}
      {runs.data?.length === 0 && (
        <div className="card">
          <Empty icon="rocket" title="Aucun run ici">
            <p>Lance un run depuis un channel : il apparaîtra ici avec son avancement en direct.</p>
            <button className="btn primary" onClick={() => launch()}>
              <Icon name="rocket" /> Nouveau run
            </button>
          </Empty>
        </div>
      )}
      <div className="run-list">
        {runs.data?.map((run) => (
          <RunRow key={run.task_id} run={run} active={run.task_id === selected} />
        ))}
      </div>

      <RunDrawer taskId={selected} onChange={runs.refresh} />
    </div>
  );
}

const STATUS_ICON: Record<Status, IconName> = { pending: "clock", working: "loader", done: "check", failed: "alert" };

function RunRow({ run, active }: { run: RunSummary; active: boolean }) {
  const params = Object.entries(run.run_params);
  return (
    <button className={`run${active ? " active" : ""}`} onClick={() => go({ page: "runs", id: run.task_id })}>
      <span className={`thumb m badge ${run.status}`} style={{ borderRadius: 14, height: 52, width: 52, padding: 0, justifyContent: "center" }}>
        <Icon name={STATUS_ICON[run.status]} size={20} className={run.status === "working" ? "spin" : undefined} />
      </span>
      <span style={{ minWidth: 0 }}>
        <div className={`run-title truncate${run.title ? "" : " placeholder"}`}>
          {run.title ?? (run.status === "failed" ? "Échec avant le titre" : run.status === "done" ? run.channel_label : "Titre à venir…")}
        </div>
        <div className="run-meta">
          <span style={{ color: "var(--text-soft)", fontWeight: 550 }}>{run.channel_label}</span>
          <span>·</span>
          <span className="mono">{run.channel_name}</span>
          {params.slice(0, 2).map(([name, value]) => (
            <span key={name} className="chip static truncate" style={{ maxWidth: 240, height: 22 }}>
              <span className="faint mono">{name}</span> {value}
            </span>
          ))}
          {params.length > 2 && <span className="faint">+{params.length - 2}</span>}
        </div>
        {run.status === "failed" && run.error_line && (
          <div className="small truncate" style={{ color: "var(--danger)", marginTop: 3 }}>{run.error_line}</div>
        )}
      </span>
      <span className="run-side">
        <span className="row">
          {run.status === "pending" && run.queue_position && <span className="faint small">#{run.queue_position}</span>}
          <StatusBadge status={run.status} stage={run.stage} />
        </span>
        <Steps status={run.status} stage={run.stage} />
        <span className="faint small nowrap" title={fullDate(run.created_at)}>
          {ago(run.created_at)}
          {run.started_at && ` · ${duration(run.started_at, run.finished_at)}`}
        </span>
      </span>
    </button>
  );
}

function RunDrawer({ taskId, onChange }: { taskId?: string; onChange: () => void }) {
  const { launch } = useStudio();
  const toast = useToast();
  const detail = usePolling<RunDetail | null>(
    () => (taskId ? api.run(taskId) : Promise.resolve(null)),
    [taskId],
    (data) => (data && (data.status === "pending" || data.status === "working") ? 3000 : null),
  );
  const run = detail.data && detail.data.task_id === taskId ? detail.data : null;
  const close = () => go({ page: "runs" });

  const remove = async () => {
    if (!run || !window.confirm("Retirer ce run de la file ?")) return;
    try {
      await api.deleteRun(run.task_id);
      toast("ok", "Run retiré de la file");
      onChange();
      close();
    } catch (err) {
      toast("error", "Impossible de retirer le run", err instanceof Error ? err.message : String(err));
      detail.refresh();
    }
  };

  return (
    <Drawer
      open={!!taskId}
      onClose={close}
      title={run ? run.title ?? run.channel_label : "Run"}
      subtitle={
        run && (
          <span className="row wrap">
            <StatusBadge status={run.status} stage={run.stage} />
            <button className="btn ghost xs mono" onClick={() => copy(run.task_id).then(() => toast("info", "Identifiant copié"))}>
              {run.task_id}
              <Icon name="copy" size={11} />
            </button>
          </span>
        )
      }
      footer={
        run &&
        (run.channel_id || run.status === "pending") && (
          <>
            {run.channel_id && (
              <a className="btn ghost" href={`#/channels/${encodeURIComponent(run.channel_id)}`}>
                <Icon name="layers" /> Channel
              </a>
            )}
            <span className="grow" />
            {run.status === "pending" && (
              <button className="btn danger" onClick={remove}>
                <Icon name="trash" /> Retirer de la file
              </button>
            )}
            {run.channel_id && (
              <button className="btn primary" onClick={() => launch({ channelId: run.channel_id!, values: run.run_params })}>
                <Icon name="refresh" /> Relancer…
              </button>
            )}
          </>
        )
      }
    >
      {detail.error && <Notice tone="error">{detail.error.message}</Notice>}
      {!run && !detail.error && (
        <div className="empty">
          <Spinner size={20} />
        </div>
      )}
      {run && <RunBody run={run} />}
    </Drawer>
  );
}

function RunBody({ run }: { run: RunDetail }) {
  const toast = useToast();
  const publication = run.result;
  return (
    <>
      {run.video_url && (
        <div className="stack" style={{ gap: 10, justifyItems: "center" }}>
          <video className="player" src={run.video_url} controls playsInline preload="metadata" />
          {run.download_url && (
            <a className="btn sm" href={run.download_url}>
              <Icon name="download" /> Télécharger la vidéo
            </a>
          )}
        </div>
      )}

      {run.status === "pending" && (
        <Notice tone="warn">
          {run.queue_position === 1 ? "Prochain run servi" : `${run.queue_position}ᵉ dans la file`}. Il partira dès que le
          worker sera libre.
        </Notice>
      )}
      {run.status === "failed" && (
        <Notice tone="error">
          <strong>Échec{run.stage ? ` pendant « ${stageLabel(run.stage)} »` : ""}.</strong> {run.error_line}
        </Notice>
      )}

      <div>
        <h4 className="section-title">Avancement</h4>
        <Stepper run={run} />
      </div>

      {(publication.description || publication.hashtags?.length) && (
        <div>
          <div className="row" style={{ marginBottom: 10 }}>
            <h4 className="section-title" style={{ margin: 0 }}>Texte de publication</h4>
            <button
              className="btn ghost xs"
              style={{ marginLeft: "auto" }}
              onClick={() =>
                copy([publication.title, publication.description, publication.hashtags?.join(" ")].filter(Boolean).join("\n\n")).then(() =>
                  toast("info", "Texte copié"),
                )
              }
            >
              <Icon name="copy" size={12} /> Copier
            </button>
          </div>
          <div className="preview-box">
            {publication.title && <strong>{publication.title}</strong>}
            <p className="preview" style={{ marginTop: 6 }}>{publication.description}</p>
            {publication.hashtags && <p style={{ color: "var(--accent)", margin: "8px 0 0" }}>{publication.hashtags.join(" ")}</p>}
          </div>
        </div>
      )}

      {Object.keys(run.run_params).length > 0 && (
        <div>
          <h4 className="section-title">Paramètres du run</h4>
          <dl className="kv">
            {Object.entries(run.run_params).map(([name, value]) => (
              <Pair key={name} label={<code>{name}</code>}>{value}</Pair>
            ))}
          </dl>
        </div>
      )}

      <div>
        <h4 className="section-title">Config</h4>
        <dl className="kv">
          <Pair label="Channel">{run.channel_label}{run.channel_version ? ` · v${run.channel_version}` : ""}</Pair>
          <Pair label="Dossier">{<code>{run.channel_name}</code>}</Pair>
          {run.avatar?.name && <Pair label="Avatar">{run.avatar.name}</Pair>}
          <Pair label="Voix">{run.avatar?.voice_url ? run.avatar.voice_url.split("/").pop() : "aucune"}</Pair>
          {run.language && <Pair label="Langue">{run.language}</Pair>}
          {run.skill && <Pair label="Style">{run.skill}</Pair>}
          {run.email && <Pair label="Livraison">{run.email}</Pair>}
        </dl>
      </div>

      {run.user_message && (
        <details>
          <summary className="section-title" style={{ cursor: "pointer" }}>Prompt envoyé à l'agent</summary>
          <pre className="block" style={{ marginTop: 10 }}>{run.user_message}</pre>
        </details>
      )}
      {run.error && (
        <details>
          <summary className="section-title" style={{ cursor: "pointer" }}>Trace complète</summary>
          <pre className="block" style={{ marginTop: 10 }}>{run.error}</pre>
        </details>
      )}
    </>
  );
}

function Pair({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function Stepper({ run }: { run: RunDetail }) {
  const order = ["planification", "rendu", "publication"];
  const index = run.stage ? order.indexOf(run.stage) : -1;
  const state = (i: number) => {
    if (run.status === "done") return "done";
    if (run.status === "pending") return "";
    if (run.status === "failed") return i < index ? "done" : i === Math.max(index, 0) ? "fail" : "";
    return i < index ? "done" : i === index ? "now" : "";
  };
  const steps: { label: string; state: string; when?: string | null; icon: IconName }[] = [
    { label: "Dans la file", state: "done", when: run.created_at, icon: "clock" },
    { label: "Planification", state: state(0), when: index === 0 ? run.stage_at : undefined, icon: "sparkles" },
    { label: "Rendu vidéo", state: state(1), when: index === 1 ? run.stage_at : undefined, icon: "film" },
    { label: "Publication", state: state(2), when: index === 2 ? run.stage_at : undefined, icon: "send" },
    {
      label: run.status === "failed" ? "Échec" : "Terminé",
      state: run.status === "done" ? "done" : run.status === "failed" ? "fail" : "",
      when: run.finished_at,
      icon: run.status === "failed" ? "alert" : "check",
    },
  ];
  return (
    <div className="stepper">
      {steps.map((step) => (
        <div key={step.label} className={`step ${step.state}`}>
          <span className="step-dot">
            <Icon name={step.state === "done" ? "check" : step.icon} size={13} className={step.state === "now" ? undefined : undefined} />
          </span>
          <span className="step-label">{step.label}</span>
          <span className="step-when">{step.when ? ago(step.when) : step.state === "now" ? "en cours…" : ""}</span>
        </div>
      ))}
      {run.started_at && (
        <p className="field-help" style={{ marginTop: 10 }}>
          Durée : {duration(run.started_at, run.finished_at)}
          {run.status === "working" && " (en cours)"}
        </p>
      )}
    </div>
  );
}
