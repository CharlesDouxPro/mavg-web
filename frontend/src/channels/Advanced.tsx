// Les réglages avancés, choisis et nommés en français. L'aide vient des docstrings du worker.

import type { AgentConfig, Json } from "../api";
import { useStudio } from "../studio";
import { Icon, type IconName } from "../ui/Icon";
import { Field, Switch } from "../ui/kit";
import { ListInput, NumberInput } from "./widgets";

type Kind =
  | { type: "int" | "float" }
  | { type: "bool" }
  | { type: "select"; options: [string, string][] }
  | { type: "color" }
  | { type: "list"; mono?: boolean };

interface Spec {
  key: string;
  label: string;
  kind: Kind;
  wide?: boolean;
}

type Section = "render" | "plan" | "subtitles" | "publication" | "llm";

const GROUPS: { section: Section; model: string; title: string; hint: string; icon: IconName; fields: Spec[] }[] = [
  {
    section: "plan",
    model: "PlanConstraints",
    title: "Durée & rythme",
    hint: "Les bornes que le plan de tournage doit respecter.",
    icon: "clock",
    fields: [
      { key: "min_total_seconds", label: "Durée totale min (s)", kind: { type: "int" } },
      { key: "max_total_seconds", label: "Durée totale max (s)", kind: { type: "int" } },
      { key: "words_per_second", label: "Débit (mots / s)", kind: { type: "float" } },
      { key: "min_shot_seconds", label: "Plan min (s)", kind: { type: "int" } },
      { key: "max_shot_seconds", label: "Plan max (s)", kind: { type: "int" } },
      { key: "min_description_words", label: "Description min (mots)", kind: { type: "int" } },
      { key: "arc", label: "Arc narratif", kind: { type: "list", mono: true }, wide: true },
      { key: "forbidden_appearance_words", label: "Mots d'apparence interdits", kind: { type: "list" }, wide: true },
    ],
  },
  {
    section: "render",
    model: "RenderSettings",
    title: "Rendu vidéo",
    hint: "Réglages du moteur MiniMax-H3, constants sur toute la vidéo.",
    icon: "film",
    fields: [
      {
        key: "aspect_ratio",
        label: "Format",
        kind: { type: "select", options: [["9:16", "9:16 · vertical"], ["3:4", "3:4"], ["1:1", "1:1 · carré"], ["4:3", "4:3"], ["16:9", "16:9 · paysage"], ["21:9", "21:9"], ["auto", "Auto"]] },
      },
      { key: "seed", label: "Seed", kind: { type: "int" } },
      { key: "num_inference_steps", label: "Pas d'inférence", kind: { type: "int" } },
      { key: "flow_shift", label: "Flow shift", kind: { type: "float" } },
      { key: "audio_flow_shift", label: "Flow shift audio", kind: { type: "float" } },
      { key: "concurrency", label: "Clips en parallèle", kind: { type: "int" } },
      { key: "timeout_s", label: "Timeout par clip (s)", kind: { type: "float" } },
    ],
  },
  {
    section: "subtitles",
    model: "SubtitleSettings",
    title: "Sous-titres",
    hint: "Transcrits en local par faster-whisper sur l'audio réel, puis incrustés.",
    icon: "file",
    fields: [
      { key: "enabled", label: "Incruster des sous-titres", kind: { type: "bool" }, wide: true },
      { key: "style", label: "Style", kind: { type: "select", options: [["karaoke", "Karaoké (mot en cours coloré)"], ["plain", "Simple"]] } },
      { key: "model", label: "Modèle whisper", kind: { type: "select", options: [["large-v3", "large-v3 · qualité"], ["large-v3-turbo", "large-v3-turbo · rapide"], ["base", "base · test"], ["tiny", "tiny · test"]] } },
      { key: "device", label: "Calcul", kind: { type: "select", options: [["auto", "Auto"], ["cuda", "GPU (cuda)"], ["cpu", "CPU"]] } },
      { key: "base_color", label: "Couleur du texte", kind: { type: "color" } },
      { key: "highlight_color", label: "Couleur du mot en cours", kind: { type: "color" } },
      { key: "max_chars", label: "Caractères par légende", kind: { type: "int" } },
      { key: "max_duration_s", label: "Durée max d'une légende (s)", kind: { type: "float" } },
      { key: "max_gap_s", label: "Silence qui coupe (s)", kind: { type: "float" } },
    ],
  },
  {
    section: "publication",
    model: "PublicationConstraints",
    title: "Texte de publication",
    hint: "Les limites du titre, de la légende et des hashtags.",
    icon: "send",
    fields: [
      { key: "min_title_chars", label: "Titre min (car.)", kind: { type: "int" } },
      { key: "max_title_chars", label: "Titre max (car.)", kind: { type: "int" } },
      { key: "min_hashtags", label: "Hashtags min", kind: { type: "int" } },
      { key: "min_chars", label: "Légende min (car.)", kind: { type: "int" } },
      { key: "max_chars", label: "Légende max (car.)", kind: { type: "int" } },
      { key: "max_hashtags", label: "Hashtags max", kind: { type: "int" } },
    ],
  },
  {
    section: "llm",
    model: "LLMSettings",
    title: "Raisonnement de l'agent",
    hint: "Le budget du modèle qui écrit le plan.",
    icon: "cpu",
    fields: [
      { key: "effort", label: "Effort", kind: { type: "select", options: [["low", "Bas"], ["medium", "Moyen"], ["high", "Élevé"], ["xhigh", "Très élevé"], ["max", "Maximum"]] } },
      { key: "max_tokens", label: "Tokens max", kind: { type: "int" } },
      { key: "max_iterations", label: "Itérations max", kind: { type: "int" } },
      { key: "thinking", label: "Réflexion étendue", kind: { type: "bool" }, wide: true },
    ],
  },
];

export function AdvancedSettings({
  agent,
  onChange,
}: {
  agent: AgentConfig;
  onChange: (section: Section, key: string, value: Json) => void;
}) {
  const { catalog } = useStudio();
  const defaults = catalog.defaults.agent_config;
  return (
    <div>
      {GROUPS.map((group) => {
        const values = agent[group.section] as Record<string, Json>;
        const changed = group.fields.filter(
          (spec) => JSON.stringify(values[spec.key]) !== JSON.stringify((defaults[group.section] as Record<string, Json>)[spec.key]),
        ).length;
        return (
          <details className="adv" key={group.section}>
            <summary>
              <span className="card-icon" style={{ width: 28, height: 28 }}>
                <Icon name={group.icon} size={14} />
              </span>
              <span>
                {group.title}
                <div className="muted small" style={{ fontWeight: 400 }}>{group.hint}</div>
              </span>
              {changed > 0 && <span className="badge accent" style={{ marginLeft: 8 }}>{changed} modifié{changed > 1 ? "s" : ""}</span>}
              <Icon name="chevron" className="chev" />
            </summary>
            <div className="adv-body grid-3">
              {group.fields.map((spec) => (
                <Field
                  key={spec.key}
                  label={spec.kind.type === "bool" ? undefined : spec.label}
                  help={catalog.help[group.model]?.[spec.key]}
                  className={spec.wide ? "wide" : undefined}
                >
                  <SettingInput
                    spec={spec}
                    value={values[spec.key]}
                    onChange={(value) => onChange(group.section, spec.key, value)}
                  />
                </Field>
              ))}
            </div>
          </details>
        );
      })}
    </div>
  );
}

function SettingInput({ spec, value, onChange }: { spec: Spec; value: Json; onChange: (next: Json) => void }) {
  const kind = spec.kind;
  if (kind.type === "bool") return <Switch checked={value === true} onChange={onChange} label={spec.label} />;
  if (kind.type === "int" || kind.type === "float")
    return <NumberInput value={value as number} integer={kind.type === "int"} onChange={(next) => next !== null && onChange(next)} />;
  if (kind.type === "select")
    return (
      <select className="input" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
        {kind.options.map(([option, label]) => (
          <option key={option} value={option}>
            {label}
          </option>
        ))}
      </select>
    );
  if (kind.type === "color")
    return (
      <div className="row">
        <input
          type="color"
          className="input"
          value={`#${String(value ?? "FFFFFF")}`}
          onChange={(e) => onChange(e.target.value.slice(1).toUpperCase())}
        />
        <input className="input mono" value={String(value ?? "")} onChange={(e) => onChange(e.target.value.replace(/^#/, "").toUpperCase())} />
      </div>
    );
  const mono = kind.type === "list" && kind.mono;
  return <ListInput values={(value as string[]) ?? []} onChange={onChange} mono={mono} placeholder="Entrée pour ajouter" />;
}
