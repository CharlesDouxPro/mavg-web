// Le formulaire : l'essentiel d'une vidéo en clair, les réglages du moteur repliés.

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, api, type FormConfig, type Issue, type JsonObject, type JsonValue } from "./api";
import { SchemaField, type FieldContext } from "./fields";
import { ParamsEditor } from "./ParamsEditor";
import { fieldPath, getIn, pathKey, resolve, same, setIn, type Path } from "./schema";

/** Sections repliées, dans l'ordre d'affichage. Un champ d'AgentConfig absent d'ici et de MAIN y est ajouté tout seul. */
const ADVANCED: [string, string][] = [
  ["models", "Modèles"],
  ["llm", "Raisonnement (LLM)"],
  ["render", "Rendu vidéo"],
  ["plan", "Contraintes du plan"],
  ["subtitles", "Sous-titres"],
  ["publication", "Texte de publication"],
  ["scraper", "Scraper"],
  ["storage", "Stockage objet"],
];
const MAIN = new Set(["skill", "language", "brief", "params", "avatar"]);

type Notice = { kind: "ok" | "error"; text: string } | null;

interface Props {
  config: FormConfig;
  onPushed: () => void;
}

export function TaskForm({ config, onPushed }: Props) {
  const { schema: root, templates } = config;
  const [templateId, setTemplateId] = useState(templates[0].id);
  const template = templates.find((t) => t.id === templateId) ?? templates[0];
  const [value, setValue] = useState<JsonObject>(template.task);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [notice, setNotice] = useState<Notice>(null);
  const [preview, setPreview] = useState<JsonObject | null>(null);
  const [busy, setBusy] = useState<"validate" | "push" | null>(null);

  const agentSchema = resolve(root, root.properties!.agent_config);
  const agentProps = agentSchema.properties ?? {};
  const advanced = [
    ...ADVANCED.filter(([key]) => key in agentProps),
    ...Object.keys(agentProps)
      .filter((key) => !MAIN.has(key) && !ADVANCED.some(([known]) => known === key))
      .map((key): [string, string] => [key, agentProps[key].title ?? key]),
  ];

  const errors = useMemo(() => {
    const byField: Record<string, string> = {};
    for (const issue of issues) {
      const key = pathKey(fieldPath(value, issue.path));
      byField[key] = byField[key] ? `${byField[key]} ${issue.message}` : issue.message;
    }
    return byField;
    // Les erreurs se rattachent aux champs au moment de la réponse du serveur.
  }, [issues]);

  const onChange = (path: Path, next: JsonValue) => {
    setValue((current) => setIn(current, path, next) as JsonObject);
    const key = pathKey(path);
    setIssues((current) => current.filter((issue) => !pathKey(issue.path).startsWith(key)));
    setPreview(null);
    setNotice((current) => (current?.kind === "ok" ? null : current));
  };

  const ctx: FieldContext = {
    root,
    value,
    onChange,
    errors,
    locked: new Set(config.locked),
    secretFields: new Set(config.secret_fields),
  };
  const field = (path: Path, label?: string, help?: ReactNode, bare = false) => (
    <SchemaField ctx={ctx} node={nodeAt(root, path)} path={path} label={label} help={help} bare={bare} />
  );

  const chooseTemplate = (id: string) => {
    const next = templates.find((t) => t.id === id)!;
    const dirty = !same(value, template.task);
    if (dirty && !window.confirm(`Repartir du modèle « ${next.label} » ? Les modifications en cours seront perdues.`)) {
      return;
    }
    setTemplateId(id);
    setValue(next.task);
    setIssues([]);
    setNotice(null);
    setPreview(null);
  };

  const submit = async (kind: "validate" | "push") => {
    setBusy(kind);
    setIssues([]);
    setNotice(null);
    try {
      if (kind === "validate") {
        const result = await api.validate(value);
        setPreview(result.document);
        setNotice({ kind: "ok", text: `Tâche valide. Elle partira sous l'identifiant ${result.task_id}.` });
      } else {
        const result = await api.push(value);
        const others = result.pending - 1;
        setNotice({
          kind: "ok",
          text:
            `${result.task_id} est en pending. ` +
            (others > 0
              ? `${others} autre(s) tâche(s) en attente : le worker prend la plus récente en premier.`
              : "C'est la seule tâche en attente."),
        });
        onPushed();
      }
    } catch (error) {
      const apiError = error instanceof ApiError ? error : new ApiError(String(error), 0);
      setIssues(apiError.issues);
      setNotice({ kind: "error", text: apiError.message });
    } finally {
      setBusy(null);
    }
  };

  const skills = [...new Set(templates.map((t) => getIn(t.task, ["agent_config", "skill"])).filter(Boolean))];
  const language = String(getIn(value, ["agent_config", "language"]) ?? "");
  const params = (getIn(value, ["agent_config", "params"]) ?? {}) as JsonObject;

  return (
    <form
      className="task-form"
      onSubmit={(e) => {
        e.preventDefault();
        void submit("push");
      }}
    >
      <section className="card">
        <div className="field">
          <label htmlFor="template">Modèle de tâche</label>
          <select id="template" value={templateId} onChange={(e) => chooseTemplate(e.target.value)}>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
          <p className="help">
            Pré-remplit tout le formulaire, options avancées comprises. Les modèles vivent dans{" "}
            <code>templates/</code>.
          </p>
        </div>
        <div className="row">
          {field(
            ["task_id"],
            "Identifiant",
            "Suffixé à l'envoi par la date (_MMJJ_HHMMSS) : repousser la même tâche n'écrase pas la précédente.",
          )}
          {field(["channel_config", "channel_name"], "Chaîne")}
        </div>
        {field(["channel_config", "email"], "Email du rapport", "Reçoit le rapport quand la vidéo est prête ou a échoué.")}
      </section>

      <section className="card">
        <h2>Brief</h2>
        {field(["agent_config", "brief", "prompt"], "Consigne", "La tâche en langage naturel, telle que l'agent la lit.")}
        {field(["agent_config", "brief", "mood"], "Ton")}
        <div className="row">
          <div className="field">
            <label htmlFor="skill">Style imposé</label>
            <input
              id="skill"
              list="skills"
              className="mono"
              value={String(getIn(value, ["agent_config", "skill"]) ?? "")}
              onChange={(e) => onChange(["agent_config", "skill"], e.target.value)}
            />
            <datalist id="skills">
              {skills.map((skill) => (
                <option key={String(skill)} value={String(skill)} />
              ))}
            </datalist>
            <p className="help">Un skill de style du worker. Vide : l'agent choisit d'après la consigne.</p>
            {errors["agent_config.skill"] && <p className="error">{errors["agent_config.skill"]}</p>}
          </div>
          <div className="field">
            <label htmlFor="language">Langue</label>
            <select id="language" value={language} onChange={(e) => onChange(["agent_config", "language"], e.target.value)}>
              <option value="">Libre (celle de la source ou du brief)</option>
              {Object.entries(config.languages).map(([code, name]) => (
                <option key={code} value={code}>
                  {code}, {name}
                </option>
              ))}
              {language && !(language in config.languages) && <option value={language}>{language}</option>}
            </select>
            <p className="help">Langue parlée et langue de la description.</p>
          </div>
        </div>
      </section>

      <section className="card">
        <h2>Sujet de la vidéo</h2>
        <p className="help">
          Ce qui distingue cette vidéo : l'URL à scraper, l'idée de DIY, le fruit à animer. Les clés sont libres ;
          l'agent les reçoit telles quelles.
        </p>
        <ParamsEditor
          value={params}
          onChange={(next) => onChange(["agent_config", "params"], next)}
          error={errors["agent_config.params"]}
        />
      </section>

      <section className="card">
        <h2>Avatar</h2>
        {field(["agent_config", "avatar"], "Avatar", undefined, true)}
      </section>

      <Collapsible
        className="card advanced"
        title="Options avancées"
        badge={advanced.filter(([key]) => changed(value, template.task, key)).length || undefined}
        forceOpen={hasErrorUnder(errors, advanced.map(([key]) => `agent_config.${key}`))}
      >
        <p className="help">
          Modèles et réglages du moteur, pré-remplis par le modèle de tâche. Les secrets s'écrivent{" "}
          <code>${"{VAR}"}</code> et se résolvent chez le worker. Variables admises :{" "}
          {config.env_refs.map((ref, i) => (
            <span key={ref}>
              {i > 0 && ", "}
              <code>{ref}</code>
            </span>
          ))}
          .
        </p>
        {advanced.map(([key, title]) => (
          <Collapsible
            key={key}
            className="sub"
            title={title}
            badge={changed(value, template.task, key) ? "modifié" : undefined}
            forceOpen={hasErrorUnder(errors, [`agent_config.${key}`])}
          >
            {field(["agent_config", key], title, undefined, true)}
          </Collapsible>
        ))}
      </Collapsible>

      <section className="card actions" aria-live="polite">
        {notice && <p className={`notice ${notice.kind}`}>{notice.text}</p>}
        {issues.length > 0 && (
          <ul className="issues">
            {issues.map((issue, index) => (
              <li key={index}>
                <code>{pathKey(issue.path) || "tâche"}</code> {issue.message}
              </li>
            ))}
          </ul>
        )}
        <div className="buttons">
          <button type="button" className="secondary" disabled={busy !== null} onClick={() => void submit("validate")}>
            {busy === "validate" ? "Vérification…" : "Vérifier"}
          </button>
          <button type="submit" disabled={busy !== null}>
            {busy === "push" ? "Envoi…" : "Pousser en pending"}
          </button>
        </div>
        <details className="preview">
          <summary>{preview ? "Document qui sera inséré" : "Aperçu de la tâche envoyée"}</summary>
          <pre>{JSON.stringify(preview ?? value, null, 2)}</pre>
        </details>
      </section>
    </form>
  );
}

function nodeAt(root: FormConfig["schema"], path: Path) {
  let node = root;
  for (const key of path) node = resolve(root, resolve(root, node).properties?.[key] ?? {});
  return node;
}

const changed = (value: JsonObject, baseline: JsonObject, key: string) =>
  !same(getIn(value, ["agent_config", key]), getIn(baseline, ["agent_config", key]));

const hasErrorUnder = (errors: Record<string, string>, prefixes: string[]) =>
  Object.keys(errors).some((key) => prefixes.some((prefix) => key === prefix || key.startsWith(`${prefix}.`)));

interface CollapsibleProps {
  title: string;
  className: string;
  badge?: string | number;
  forceOpen: boolean;
  children: ReactNode;
}

/** Un `<details>` qui s'ouvre de lui-même quand une erreur tombe dedans, et que l'on peut refermer. */
function Collapsible({ title, className, badge, forceOpen, children }: CollapsibleProps) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (forceOpen) setOpen(true);
  }, [forceOpen]);
  return (
    <details className={className} open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        <span>{title}</span>
        {badge !== undefined && (
          <span className="badge">{typeof badge === "number" ? `${badge} modifiée(s)` : badge}</span>
        )}
      </summary>
      <div className="collapsible-body">{children}</div>
    </details>
  );
}
