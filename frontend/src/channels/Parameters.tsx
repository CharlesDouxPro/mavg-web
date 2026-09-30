// Les paramètres de run d'un channel : ce que le formulaire de lancement demandera.

import type { ChannelParameter, Issue, ParamType } from "../api";
import { countUses } from "../lib/data";
import { useStudio } from "../studio";
import { Icon } from "../ui/Icon";
import { Field, Switch, issueFor } from "../ui/kit";
import { NumberInput } from "./widgets";

export const PARAM_PRESETS: { label: string; parameter: ChannelParameter }[] = [
  {
    label: "Lien d'article",
    parameter: { name: "source_url", type: "url", default: "", required: true, description: "L'article dont la vidéo parle." },
  },
  {
    label: "Texte fourni",
    parameter: {
      name: "source_text",
      type: "text",
      default: "",
      required: false,
      description: "Le texte de l'article : s'il est fourni, l'agent n'ira pas scraper le lien.",
    },
  },
  { label: "Idée", parameter: { name: "idee", type: "string", default: "", required: true, description: "Le sujet de la vidéo." } },
];

export function ParameterValueInput({
  type,
  value,
  onChange,
  placeholder,
}: {
  type: ParamType;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
}) {
  if (type === "boolean")
    return (
      <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">—</option>
        <option value="true">Oui</option>
        <option value="false">Non</option>
      </select>
    );
  if (type === "number")
    return (
      <NumberInput
        value={value === "" ? null : Number(value.replace(",", "."))}
        nullable
        placeholder={placeholder}
        onChange={(next) => onChange(next === null ? "" : String(next))}
      />
    );
  if (type === "text")
    return (
      <textarea className="input" rows={3} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    );
  return (
    <input
      className={`input${type === "url" ? " mono" : ""}`}
      value={value}
      placeholder={placeholder ?? (type === "url" ? "https://…" : undefined)}
      onChange={(e) => onChange(e.target.value)}
      inputMode={type === "url" ? "url" : undefined}
    />
  );
}

export function ParametersEditor({
  parameters,
  templates,
  issues,
  warnings,
  onChange,
  onRename,
}: {
  parameters: ChannelParameter[];
  templates: string[];
  issues: Issue[];
  warnings: Issue[];
  onChange: (next: ChannelParameter[]) => void;
  onRename: (old: string, next: string) => void;
}) {
  const { catalog } = useStudio();
  const update = (index: number, patch: Partial<ChannelParameter>) =>
    onChange(parameters.map((parameter, i) => (i === index ? { ...parameter, ...patch } : parameter)));
  const names = parameters.map((parameter) => parameter.name);
  const add = (parameter: ChannelParameter) => {
    let name = parameter.name;
    for (let n = 2; names.includes(name); n++) name = `${parameter.name}_${n}`;
    onChange([...parameters, { ...parameter, name }]);
  };

  return (
    <div className="stack" style={{ gap: 12 }}>
      {parameters.length === 0 && (
        <p className="muted small" style={{ margin: 0 }}>
          Aucun paramètre : chaque run lancera exactement ce brief. Ajoute-en pour faire varier la vidéo d'un run à
          l'autre (un lien, une idée, un angle…).
        </p>
      )}
      <div>
        {parameters.map((parameter, index) => {
          const uses = countUses(templates, parameter.name);
          const base = `parameters.${index}`;
          return (
            <div className="param-row" key={index}>
              <Field error={issueFor(issues, `${base}.name`)} warning={issueFor(warnings, `${base}.name`)}>
                <input
                  className="input mono"
                  value={parameter.name}
                  placeholder="nom_du_parametre"
                  onChange={(e) => {
                    const next = e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_");
                    onRename(parameter.name, next);
                    update(index, { name: next });
                  }}
                />
              </Field>
              <select
                className="input"
                value={parameter.type}
                onChange={(e) => update(index, { type: e.target.value as ParamType, default: "" })}
              >
                {Object.entries(catalog.param_types).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <Field error={issueFor(issues, `${base}.default`)}>
                <ParameterValueInput
                  type={parameter.type}
                  value={parameter.default}
                  placeholder="Valeur par défaut"
                  onChange={(next) => update(index, { default: next })}
                />
              </Field>
              <div style={{ height: 38, display: "flex", alignItems: "center" }}>
                <Switch checked={parameter.required} onChange={(required) => update(index, { required })} label="Requis" />
              </div>
              <button
                type="button"
                className="btn ghost icon danger"
                onClick={() => onChange(parameters.filter((_, i) => i !== index))}
                aria-label={`Supprimer ${parameter.name}`}
              >
                <Icon name="trash" />
              </button>
              <div className="desc row">
                <input
                  className="input grow"
                  value={parameter.description}
                  placeholder="Aide affichée dans le formulaire de lancement"
                  onChange={(e) => update(index, { description: e.target.value })}
                />
                <span className={`usage ${uses ? "" : "faint"}`}>
                  <Icon name="braces" size={13} />
                  {uses ? `cité ${uses}×` : "non cité"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      <div className="row wrap">
        <button
          type="button"
          className="btn sm"
          onClick={() => add({ name: "parametre", type: "string", default: "", required: false, description: "" })}
        >
          <Icon name="plus" />
          Ajouter un paramètre
        </button>
        <span className="faint small">ou</span>
        {PARAM_PRESETS.filter((preset) => !names.includes(preset.parameter.name)).map((preset) => (
          <button key={preset.label} type="button" className="btn ghost sm" onClick={() => add(preset.parameter)}>
            <Icon name="plus" size={13} />
            {preset.label}
          </button>
        ))}
      </div>
    </div>
  );
}
