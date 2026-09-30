// Les champs de l'éditeur de channel : nombre tolérant, liste, textarea à ${…} surlignés.

import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import { PARAM_NAME } from "../lib/data";
import { Icon } from "../ui/Icon";

/** Un nombre saisi au clavier : « 1, » reste affiché le temps de taper « 1,5 ». */
export function NumberInput({
  value,
  onChange,
  integer,
  placeholder,
  nullable,
}: {
  value: number | null | undefined;
  onChange: (next: number | null) => void;
  integer?: boolean;
  placeholder?: string;
  nullable?: boolean;
}) {
  const format = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(v).replace(".", ","));
  const [text, setText] = useState(format(value));
  useEffect(() => {
    const parsed = parse(text);
    if (parsed !== value && !(parsed === null && value === undefined)) setText(format(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  const parse = (raw: string): number | null | undefined => {
    const clean = raw.trim().replace(",", ".");
    if (clean === "") return nullable ? null : undefined;
    const number = Number(clean);
    if (!Number.isFinite(number) || (integer && !Number.isInteger(number))) return undefined;
    return number;
  };
  return (
    <input
      className="input"
      inputMode={integer ? "numeric" : "decimal"}
      value={text}
      placeholder={placeholder}
      onChange={(e) => {
        setText(e.target.value);
        const parsed = parse(e.target.value);
        if (parsed !== undefined) onChange(parsed);
      }}
      onBlur={() => setText(format(value))}
    />
  );
}

/** Une liste de valeurs courtes, en puces : Entrée ajoute, × retire. */
export function ListInput({
  values,
  onChange,
  placeholder,
  mono,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  mono?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const value = draft.trim();
    if (value && !values.includes(value)) onChange([...values, value]);
    setDraft("");
  };
  const onKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      add();
    } else if (event.key === "Backspace" && !draft && values.length) {
      onChange(values.slice(0, -1));
    }
  };
  return (
    <div className="input" style={{ height: "auto", minHeight: 38, padding: 5, display: "flex", flexWrap: "wrap", gap: 5, alignItems: "center" }}>
      {values.map((value, index) => (
        <span key={`${value}-${index}`} className="chip static" style={mono ? { fontFamily: "var(--mono)" } : undefined}>
          {value}
          <button
            type="button"
            className="btn ghost xs icon"
            style={{ width: 18, height: 18 }}
            onClick={() => onChange(values.filter((_, i) => i !== index))}
            aria-label={`Retirer ${value}`}
          >
            <Icon name="x" size={12} />
          </button>
        </span>
      ))}
      <input
        value={draft}
        placeholder={values.length ? "" : placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
        onBlur={add}
        style={{ flex: 1, minWidth: 120, border: 0, background: "transparent", outline: "none", height: 26, padding: "0 6px" }}
      />
    </div>
  );
}

/**
 * Un textarea qui surligne ses `${paramètres}` : un calque de rendu, aligné au pixel,
 * sous un textarea au texte opaque et au fond transparent.
 */
export function TemplateArea({
  value,
  onChange,
  declared,
  placeholder,
  invalid,
  minHeight = 150,
  areaRef,
  footer,
}: {
  value: string;
  onChange: (next: string) => void;
  declared: string[];
  placeholder?: string;
  invalid?: boolean;
  minHeight?: number;
  areaRef?: RefObject<HTMLTextAreaElement | null>;
  footer?: ReactNode;
}) {
  const layer = useRef<HTMLDivElement>(null);
  const own = useRef<HTMLTextAreaElement>(null);
  const ref = areaRef ?? own;

  useLayoutEffect(() => {
    const area = ref.current;
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${Math.max(minHeight, area.scrollHeight + 2)}px`;
  }, [value, minHeight, ref]);

  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of value.matchAll(/\$\{([^{}]*)\}?/g)) {
    const start = match.index ?? 0;
    parts.push(value.slice(last, start));
    const ok = match[0].endsWith("}") && PARAM_NAME.test(match[1]) && declared.includes(match[1]);
    parts.push(
      <mark key={start} className={ok ? undefined : "bad"}>
        {match[0]}
      </mark>,
    );
    last = start + match[0].length;
  }
  parts.push(value.slice(last) + "​");

  return (
    <div className={`hl${invalid ? " invalid" : ""}`}>
      <div className="hl-layer" ref={layer} aria-hidden>
        {parts}
      </div>
      <textarea
        ref={ref}
        value={value}
        placeholder={placeholder}
        spellCheck
        style={{ minHeight }}
        onChange={(e) => onChange(e.target.value)}
        onScroll={(e) => {
          if (layer.current) layer.current.scrollTop = e.currentTarget.scrollTop;
        }}
      />
      {footer && <div className="hl-foot">{footer}</div>}
    </div>
  );
}

/** Insère `text` au curseur du textarea, et y replace le curseur. */
export function insertAt(area: HTMLTextAreaElement | null, value: string, text: string): string {
  if (!area) return value + text;
  const start = area.selectionStart ?? value.length;
  const end = area.selectionEnd ?? value.length;
  const next = value.slice(0, start) + text + value.slice(end);
  requestAnimationFrame(() => {
    area.focus();
    area.setSelectionRange(start + text.length, start + text.length);
  });
  return next;
}
