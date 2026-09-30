// Les briques de l'interface : champs, interrupteurs, badges, états vides, médias.

import type { ReactNode } from "react";
import type { Issue, Status } from "../api";
import { STATUS_LABEL } from "../lib/format";
import { Icon, type IconName } from "./Icon";

export interface FieldProps {
  label?: ReactNode;
  help?: ReactNode;
  required?: boolean;
  error?: string;
  warning?: string;
  children: ReactNode;
  className?: string;
}

export function Field({ label, help, required, error, warning, children, className }: FieldProps) {
  return (
    <div className={`field${error ? " invalid" : ""}${className ? ` ${className}` : ""}`}>
      {label && (
        <label className="field-label">
          {label}
          {required && <span className="req">*</span>}
        </label>
      )}
      {children}
      {error && (
        <p className="field-msg error">
          <Icon name="alert" size={13} />
          {error}
        </p>
      )}
      {!error && warning && (
        <p className="field-msg warn">
          <Icon name="info" size={13} />
          {warning}
        </p>
      )}
      {help && <p className="field-help">{help}</p>}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label?: ReactNode;
}) {
  return (
    <label className="switch">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="switch-track" />
      {label && <span>{label}</span>}
    </label>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (next: T) => void;
}) {
  return (
    <div className="segmented" role="tablist">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={option.value === value ? "on" : undefined}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function StatusBadge({ status, stage }: { status: Status; stage?: string | null }) {
  const label = status === "working" && stage ? stageLabel(stage) : STATUS_LABEL[status] ?? status;
  return (
    <span className={`badge ${status}`}>
      <span className="dot" />
      {label}
    </span>
  );
}

export const STAGES = ["planification", "rendu", "publication"] as const;
const STAGE_LABEL: Record<string, string> = {
  planification: "Planification",
  rendu: "Rendu vidéo",
  publication: "Publication",
  validation: "Validation",
};
export const stageLabel = (stage: string) => STAGE_LABEL[stage] ?? stage;

/** Les trois barres d'avancement d'un run : planification, rendu, publication. */
export function Steps({ status, stage }: { status: Status; stage: string | null }) {
  const index = stage ? STAGES.indexOf(stage as (typeof STAGES)[number]) : -1;
  return (
    <span className="steps" aria-hidden>
      {STAGES.map((_, i) => {
        let state = "";
        if (status === "done") state = "done";
        else if (status === "failed") state = i < index ? "done" : i === index || (index < 0 && i === 0) ? "fail" : "";
        else if (status === "working") state = i < index ? "done" : i === index ? "now" : "";
        return <i key={i} className={state} />;
      })}
    </span>
  );
}

export function Empty({ icon, title, children }: { icon: IconName; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon name={icon} size={24} />
      </div>
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Notice({ tone, children }: { tone: "warn" | "error" | "info"; children: ReactNode }) {
  const icon: IconName = tone === "info" ? "info" : "alert";
  return (
    <div className={`notice ${tone}`}>
      <Icon name={icon} />
      <div className="grow">{children}</div>
    </div>
  );
}

/** Une vignette d'avatar : l'image, ou la vidéo figée sur sa frame de référence. */
export function Media({
  url,
  kind,
  at,
  className = "thumb s",
}: {
  url: string | null | undefined;
  kind: "image" | "video";
  at?: number | null;
  className?: string;
}) {
  if (!url)
    return (
      <span className={className}>
        <Icon name="user" size={18} />
      </span>
    );
  return (
    <span className={className}>
      {kind === "video" ? (
        <video src={`${url}#t=${at ?? 0.5}`} muted playsInline preload="metadata" />
      ) : (
        <img src={url} alt="" loading="lazy" />
      )}
    </span>
  );
}

export function mediaKind(uri: string): "image" | "video" {
  return /\.(mp4|mov|webm)$/i.test(uri) ? "video" : "image";
}

/** L'erreur ou l'avertissement rattaché à un chemin de champ. */
export function issueFor(issues: Issue[], key: string): string | undefined {
  return issues.find((issue) => issue.key === key)?.message;
}
