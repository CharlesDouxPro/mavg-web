// Un champ de formulaire déduit du schéma : texte, nombre, liste, choix, case, ou groupe.
// Les options avancées sont entièrement rendues par ce composant : un réglage ajouté à
// task_config.py apparaît dans le formulaire sans toucher au front.

import { useEffect, useState, type ReactNode } from "react";
import type { JsonSchema, JsonValue } from "./api";
import { getIn, pathKey, same, unwrapNullable, type Path } from "./schema";

export interface FieldContext {
  root: JsonSchema;
  value: JsonValue;
  onChange: (path: Path, next: JsonValue) => void;
  errors: Record<string, string>;
  locked: Set<string>;
  secretFields: Set<string>;
}

/** Champs texte qui méritent plusieurs lignes, où qu'ils soient dans la tâche. */
const MULTILINE = new Set(["prompt", "description", "appearance"]);

interface FieldProps {
  ctx: FieldContext;
  node: JsonSchema;
  path: Path;
  label?: string;
  help?: ReactNode;
  /** Pour un groupe : ses champs seuls, sans cadre ni titre (la section qui l'entoure en a un). */
  bare?: boolean;
}

export function SchemaField({ ctx, node, path, label, help, bare }: FieldProps) {
  const { schema, nullable } = unwrapNullable(ctx.root, node);
  const key = pathKey(path);
  const name = String(path[path.length - 1]);
  const value = getIn(ctx.value, path);
  const error = ctx.errors[key];

  if (schema.type === "object" && schema.properties) {
    // Le titre d'un `$ref` est le nom de la classe (ModelConfig pour les quatre modèles) :
    // on nomme le groupe d'après son champ. Sa docstring de classe ne sert qu'en tête de section.
    const title = label ?? humanize(name);
    const description = help ?? (bare ? schema.description : node.description);
    const fields = (
      <div className="fields">
        {Object.entries(schema.properties).map(([child, childNode]) => (
          <SchemaField key={child} ctx={ctx} node={childNode} path={[...path, child]} />
        ))}
      </div>
    );
    const intro = (
      <>
        {description && <p className="help">{description}</p>}
        {error && <p className="error">{error}</p>}
      </>
    );
    return bare ? (
      <div className="group-bare">
        {intro}
        {fields}
      </div>
    ) : (
      <fieldset className="group">
        <legend>{title}</legend>
        {intro}
        {fields}
      </fieldset>
    );
  }

  const title = label ?? schema.title ?? name;
  const description = help ?? schema.description;

  const id = `field-${key}`;
  const locked = ctx.locked.has(key);
  const secret = ctx.secretFields.has(name);
  const set = (next: JsonValue) => ctx.onChange(path, next);
  const common = { id, disabled: locked, "aria-invalid": error ? true : undefined };

  if (schema.type === "boolean") {
    return (
      <div className={`field checkbox${error ? " invalid" : ""}`} title={key}>
        <label htmlFor={id}>
          <input {...common} type="checkbox" checked={value === true} onChange={(e) => set(e.target.checked)} />
          {title}
        </label>
        {description && <p className="help">{description}</p>}
        {error && <p className="error">{error}</p>}
      </div>
    );
  }

  let control: ReactNode;
  let hint: ReactNode = null;
  if (schema.enum) {
    control = (
      <select {...common} value={String(value ?? "")} onChange={(e) => set(e.target.value || null)}>
        {nullable && <option value="">(vide)</option>}
        {schema.enum.map((option) => (
          <option key={String(option)} value={String(option)}>
            {String(option)}
          </option>
        ))}
      </select>
    );
  } else if (schema.type === "integer" || schema.type === "number") {
    control = (
      <DraftInput
        {...common}
        value={value}
        onValue={set}
        format={(v) => (v === null || v === undefined ? "" : String(v))}
        parse={parseNumber}
        inputMode={schema.type === "integer" ? "numeric" : "decimal"}
        placeholder={nullable ? "vide" : undefined}
      />
    );
  } else if (schema.type === "array") {
    hint = "Une valeur par ligne.";
    control = (
      <DraftInput
        {...common}
        multiline
        value={value}
        onValue={set}
        format={(v) => (Array.isArray(v) ? v.join("\n") : "")}
        parse={(text) => text.split("\n").map((line) => line.trim()).filter(Boolean)}
      />
    );
  } else if (schema.type === "string") {
    const text = typeof value === "string" ? value : "";
    control = MULTILINE.has(name) ? (
      <textarea {...common} rows={rowsFor(text)} value={text} onChange={(e) => set(e.target.value)} />
    ) : (
      <input
        {...common}
        className={secret ? "mono" : undefined}
        value={text}
        placeholder={secret ? "${NOM_DE_VARIABLE}" : undefined}
        spellCheck={!secret}
        onChange={(e) => set(e.target.value)}
      />
    );
    if (secret) hint = "Référence à une variable du worker, jamais la valeur du secret.";
  } else {
    // Type que le formulaire ne sait pas décomposer : on l'édite en JSON.
    hint = "JSON.";
    control = (
      <DraftInput
        {...common}
        multiline
        className="mono"
        value={value}
        onValue={set}
        format={(v) => JSON.stringify(v ?? null, null, 2)}
        parse={(text) => {
          try {
            return JSON.parse(text) as JsonValue;
          } catch {
            return text;
          }
        }}
      />
    );
  }

  return (
    <div className={`field${error ? " invalid" : ""}${locked ? " locked" : ""}`} title={key}>
      <label htmlFor={id}>{title}</label>
      {control}
      {locked && <p className="help">Réglage de la machine du worker, verrouillé.</p>}
      {hint && !locked && <p className="help">{hint}</p>}
      {description && <p className="help">{description}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

const humanize = (name: string) => {
  const words = name.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
};

/** Une virgule française vaut un point. Un texte qui n'est pas un nombre part tel quel : le serveur le refusera avec son message. */
function parseNumber(text: string): JsonValue {
  const trimmed = text.trim().replace(",", ".");
  if (trimmed === "") return null;
  const number = Number(trimmed);
  return Number.isFinite(number) ? number : text;
}

export function rowsFor(text: string) {
  const lines = text.split("\n").reduce((sum, line) => sum + Math.max(1, Math.ceil(line.length / 70)), 0);
  return Math.min(10, Math.max(2, lines));
}

interface DraftProps {
  id: string;
  value: JsonValue | undefined;
  onValue: (next: JsonValue) => void;
  format: (value: JsonValue | undefined) => string;
  parse: (text: string) => JsonValue;
  multiline?: boolean;
  disabled?: boolean;
  className?: string;
  inputMode?: "numeric" | "decimal";
  placeholder?: string;
  "aria-invalid"?: boolean;
}

/**
 * Un champ dont le texte affiché n'est pas la valeur (« 1, » pour 1, des lignes pour une
 * liste). Le brouillon garde ce que l'utilisateur tape ; il n'est réécrit que si la valeur
 * change d'ailleurs, par exemple au changement de modèle.
 */
function DraftInput({ value, onValue, format, parse, multiline, ...rest }: DraftProps) {
  const [draft, setDraft] = useState(() => format(value));
  useEffect(() => {
    // Seule la valeur externe déclenche la resynchronisation, pas la frappe.
    if (!same(parse(draft), value ?? null)) setDraft(format(value));
  }, [value]);
  const change = (text: string) => {
    setDraft(text);
    onValue(parse(text));
  };
  return multiline ? (
    <textarea {...rest} rows={rowsFor(draft)} value={draft} onChange={(e) => change(e.target.value)} />
  ) : (
    <input {...rest} value={draft} onChange={(e) => change(e.target.value)} />
  );
}
