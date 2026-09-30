// `agent_config.params` : le sujet précis de la vidéo, en paires clé / valeur libres.

import { useEffect, useRef, useState } from "react";
import type { JsonObject, JsonValue } from "./api";
import { rowsFor } from "./fields";
import { same } from "./schema";

interface Row {
  id: number;
  key: string;
  value: string;
}

interface Props {
  value: JsonObject;
  onChange: (next: JsonObject) => void;
  error?: string;
}

// L'agent lit les params comme du texte (`str(value)`) : l'éditeur ne gère que des chaînes.
const toText = (value: JsonValue) => (typeof value === "string" ? value : JSON.stringify(value));

function toObject(rows: Row[]): JsonObject {
  const object: JsonObject = {};
  for (const row of rows) if (row.key.trim()) object[row.key.trim()] = row.value;
  return object;
}

export function ParamsEditor({ value, onChange, error }: Props) {
  const nextId = useRef(0);
  const fromValue = (object: JsonObject) =>
    Object.entries(object).map(([key, item]) => ({ id: nextId.current++, key, value: toText(item) }));
  const [rows, setRows] = useState<Row[]>(() => fromValue(value));

  useEffect(() => {
    // Une ligne sans clé n'existe que dans l'éditeur : elle ne doit pas déclencher de reset.
    if (!same(toObject(rows), value)) setRows(fromValue(value));
  }, [value]);

  const update = (next: Row[]) => {
    setRows(next);
    onChange(toObject(next));
  };
  const edit = (id: number, patch: Partial<Row>) =>
    update(rows.map((row) => (row.id === id ? { ...row, ...patch } : row)));

  const keys = rows.map((row) => row.key.trim());
  const duplicated = new Set(keys.filter((key, index) => key && keys.indexOf(key) !== index));

  return (
    <div className={`params${error ? " invalid" : ""}`}>
      {rows.map((row) => (
        <div className="param-row" key={row.id}>
          <input
            className="mono param-key"
            aria-label="Clé"
            placeholder="clé"
            value={row.key}
            aria-invalid={duplicated.has(row.key.trim()) || undefined}
            onChange={(e) => edit(row.id, { key: e.target.value })}
          />
          <textarea
            aria-label={`Valeur de ${row.key || "la clé"}`}
            placeholder="valeur"
            rows={Math.min(8, rowsFor(row.value) - 1)}
            value={row.value}
            onChange={(e) => edit(row.id, { value: e.target.value })}
          />
          <button
            type="button"
            className="ghost icon"
            aria-label={`Retirer ${row.key || "la ligne"}`}
            title="Retirer"
            onClick={() => update(rows.filter((other) => other.id !== row.id))}
          >
            ×
          </button>
        </div>
      ))}
      {duplicated.size > 0 && (
        <p className="error">Clé en double : {[...duplicated].join(", ")}. Seule la dernière est gardée.</p>
      )}
      {error && <p className="error">{error}</p>}
      <button
        type="button"
        className="ghost"
        onClick={() => setRows([...rows, { id: nextId.current++, key: "", value: "" }])}
      >
        + Ajouter un paramètre
      </button>
    </div>
  );
}
