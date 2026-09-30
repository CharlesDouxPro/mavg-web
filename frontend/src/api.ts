// Le contrat avec l'API FastAPI (app/main.py).

export type JsonValue = string | number | boolean | null | JsonValue[] | JsonObject;
export type JsonObject = { [key: string]: JsonValue };

/** Le sous-ensemble de JSON Schema que pydantic produit pour TaskCreate. */
export interface JsonSchema {
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  additionalProperties?: boolean | JsonSchema;
  items?: JsonSchema;
  enum?: JsonValue[];
  anyOf?: JsonSchema[];
  default?: JsonValue;
}

export interface TaskTemplate {
  id: string;
  label: string;
  task: JsonObject;
}

export interface FormConfig {
  schema: JsonSchema;
  templates: TaskTemplate[];
  languages: Record<string, string>;
  locked: string[];
  secret_fields: string[];
  env_refs: string[];
}

export type TaskStatus = "pending" | "working" | "failed" | "done";

export interface TaskSummary {
  task_id: string;
  status: TaskStatus;
  created_at: string | null;
  channel_name: string;
  error: string | null;
}

export interface Issue {
  path: (string | number)[];
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly issues: Issue[];

  constructor(message: string, status: number, issues: Issue[] = []) {
    super(message);
    this.status = status;
    this.issues = issues;
  }
}

interface RawIssue {
  loc?: (string | number)[];
  msg?: string;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...init });
  } catch {
    throw new ApiError("Serveur injoignable.", 0);
  }
  const body = await response.json().catch(() => null);
  if (response.ok) return body as T;

  const detail = body?.detail;
  if (Array.isArray(detail)) {
    // Erreurs de validation (422) : `loc` commence par "body", la suite est le chemin du champ.
    const issues = (detail as RawIssue[]).map((raw) => ({
      path: (raw.loc ?? []).filter((part, index) => !(index === 0 && part === "body")),
      message: (raw.msg ?? "Valeur invalide").replace(/^Value error, /, ""),
    }));
    const count = issues.length;
    throw new ApiError(
      count === 1 ? "1 champ à corriger." : `${count} champs à corriger.`,
      response.status,
      issues,
    );
  }
  throw new ApiError(
    typeof detail === "string" ? detail : `Erreur ${response.status}`,
    response.status,
  );
}

const post = (task: JsonObject): RequestInit => ({ method: "POST", body: JSON.stringify(task) });

export const api = {
  form: () => request<FormConfig>("/api/form"),
  tasks: (limit = 20) => request<TaskSummary[]>(`/api/tasks?limit=${limit}`),
  validate: (task: JsonObject) =>
    request<{ task_id: string; document: JsonObject }>("/api/tasks/validate", post(task)),
  push: (task: JsonObject) =>
    request<{ task_id: string; pending: number }>("/api/tasks", post(task)),
};
