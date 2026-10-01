// Édition immuable d'un brouillon par chemin, et lecture des ${paramètres}.

export type Path = (string | number)[];

export function setIn<T>(value: T, path: Path, next: unknown): T {
  if (path.length === 0) return next as T;
  const [head, ...rest] = path;
  if (Array.isArray(value)) {
    const copy = [...value];
    copy[head as number] = setIn(copy[head as number], rest, next);
    return copy as T;
  }
  const object = (value && typeof value === "object" ? value : {}) as Record<string | number, unknown>;
  return { ...object, [head]: setIn(object[head], rest, next) } as T;
}

export function getIn(value: unknown, path: Path): unknown {
  let current = value;
  for (const key of path) {
    if (current === null || typeof current !== "object") return undefined;
    current = (current as Record<string | number, unknown>)[key];
  }
  return current;
}

export const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
export const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

export const PARAM_NAME = /^[a-z][a-z0-9_]{0,39}$/;
export const TOKEN = /\$\{([^{}]*)\}?/g;

/** Le paramètre cité seul dans `text` (`${personnage}`), ou null : l'avatar fourni par un run. */
export function soleToken(text: string): string | null {
  return /^\$\{([a-z][a-z0-9_]{0,39})\}$/.exec(text.trim())?.[1] ?? null;
}

/** Combien de fois `${name}` est cité dans les champs gabarits. */
export function countUses(texts: string[], name: string): number {
  const needle = `\${${name}}`;
  return texts.reduce((total, text) => total + text.split(needle).length - 1, 0);
}

/** Renomme les citations `${old}` en `${next}`. */
export function renameToken(text: string, old: string, next: string): string {
  return text.split(`\${${old}}`).join(`\${${next}}`);
}

export interface Segment {
  text: string;
  kind: "text" | "value" | "missing";
}

/** Découpe un texte rendu : les valeurs du run d'un côté, les `${…}` restés sans valeur de l'autre. */
export function highlight(text: string, values: string[]): Segment[] {
  const needles = [...new Set(values.filter((value) => value.trim().length >= 2))].sort((a, b) => b.length - a.length);
  const escaped = needles.map((value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const pattern = new RegExp([String.raw`\$\{[a-z][a-z0-9_]*\}`, ...escaped].join("|"), "g");
  const segments: Segment[] = [];
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index ?? 0;
    if (start > last) segments.push({ text: text.slice(last, start), kind: "text" });
    segments.push({ text: match[0], kind: match[0].startsWith("${") ? "missing" : "value" });
    last = start + match[0].length;
  }
  if (last < text.length) segments.push({ text: text.slice(last), kind: "text" });
  return segments;
}
