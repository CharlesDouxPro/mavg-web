// Lecture du schéma pydantic et accès par chemin dans la tâche en cours d'édition.

import type { JsonObject, JsonSchema, JsonValue } from "./api";

export type Path = (string | number)[];

export const pathKey = (path: Path) => path.join(".");

/** Suit un `$ref` vers `$defs`. Les clés voisines du `$ref` (la description du champ) priment. */
export function resolve(root: JsonSchema, node: JsonSchema): JsonSchema {
  if (!node.$ref) return node;
  const { $ref, ...siblings } = node;
  const target = root.$defs?.[$ref.replace("#/$defs/", "")] ?? {};
  return { ...resolve(root, target), ...siblings };
}

/** `float | None` devient le type non nul, plus le droit de laisser le champ vide. */
export function unwrapNullable(
  root: JsonSchema,
  node: JsonSchema,
): { schema: JsonSchema; nullable: boolean } {
  const resolved = resolve(root, node);
  if (!resolved.anyOf) return { schema: resolved, nullable: false };
  const options = resolved.anyOf.filter((option) => option.type !== "null");
  const nullable = options.length < resolved.anyOf.length;
  if (options.length !== 1) return { schema: resolved, nullable };
  const { anyOf: _, ...rest } = resolved;
  return { schema: { ...resolve(root, options[0]), ...rest }, nullable };
}

export function getIn(value: JsonValue | undefined, path: Path): JsonValue | undefined {
  let current = value;
  for (const key of path) {
    if (current === null || typeof current !== "object") return undefined;
    current = (current as Record<string | number, JsonValue>)[key];
  }
  return current;
}

export function setIn(value: JsonValue | undefined, path: Path, next: JsonValue): JsonValue {
  if (path.length === 0) return next;
  const [head, ...rest] = path;
  if (Array.isArray(value)) {
    const copy = [...value];
    copy[head as number] = setIn(copy[head as number], rest, next);
    return copy;
  }
  const object = value && typeof value === "object" ? value : {};
  return { ...object, [head]: setIn((object as JsonObject)[head], rest, next) };
}

/**
 * Le champ auquel rattacher une erreur. Pour une union, pydantic descend jusqu'au type
 * essayé (`reference_frame_s.float`) : on remonte jusqu'à un chemin qui existe.
 */
export function fieldPath(value: JsonValue, loc: Path): Path {
  const path = [...loc];
  while (path.length > 0 && getIn(value, path) === undefined) path.pop();
  return path;
}

export const same = (a: JsonValue | undefined, b: JsonValue | undefined) =>
  JSON.stringify(a) === JSON.stringify(b);
