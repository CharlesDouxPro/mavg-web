// Le contrat avec l'API FastAPI (app/routers/*).

export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
export type Status = "pending" | "working" | "failed" | "done";
export type ParamType = "string" | "text" | "url" | "number" | "boolean";

export interface ChannelParameter {
  name: string;
  type: ParamType;
  default: string;
  required: boolean;
  description: string;
}

export interface ModelChoice {
  provider: string;
  model_name: string;
}

export interface Avatar {
  name: string;
  avatar_url: string;
  description: string;
  appearance: string;
  reference_frame_s: number | null;
  voice_url: string;
}

export type Settings = Record<string, Json>;

export interface AgentConfig {
  skill: string;
  language: string;
  brief: { prompt: string; mood: string };
  avatar: Avatar;
  models: { master_mind: ModelChoice; slm: ModelChoice; video_generator: ModelChoice };
  llm: Settings;
  render: Settings;
  plan: Settings;
  publication: Settings & { must_include: string[] };
  subtitles: Settings;
}

export interface ChannelData {
  id: string;
  name: string;
  description: string;
  channel_config: { channel_name: string; email: string };
  parameters: ChannelParameter[];
  agent_config: AgentConfig;
}

export interface Channel extends ChannelData {
  version: number;
  created_at: string;
  updated_at: string;
}

export interface MediaRef {
  uri: string;
  url: string | null;
  kind: "image" | "video";
}

export interface ChannelSummary {
  id: string;
  name: string;
  description: string;
  channel_name: string;
  language: string;
  skill: string;
  parameters: string[];
  avatar: MediaRef | null;
  version: number;
  updated_at: string;
  runs: number;
  last_run: { task_id: string; status: Status; created_at: string } | null;
}

export interface Catalog {
  skills: { name: string; tag: string; summary: string }[];
  languages: Record<string, string>;
  providers: { id: string; label: string; models: string[] }[];
  param_types: Record<ParamType, string>;
  defaults: { agent_config: AgentConfig };
  help: Record<string, Record<string, string>>;
  storage: boolean;
}

export interface RunSummary {
  task_id: string;
  status: Status;
  stage: string | null;
  stage_at: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  channel_id: string | null;
  channel_label: string;
  channel_name: string;
  title: string | null;
  has_video: boolean;
  error_line: string | null;
  run_params: Record<string, string>;
  queue_position: number | null;
}

export interface RunDetail extends RunSummary {
  channel_version: number | null;
  email: string | null;
  skill: string;
  language: string;
  brief: { prompt?: string; mood?: string };
  avatar: Partial<Avatar>;
  user_message: string | null;
  result: { title?: string; description?: string; hashtags?: string[]; video_uri?: string };
  error: string | null;
  video_url: string | null;
  download_url: string | null;
  avatar_url: string | null;
}

export interface Preview {
  prompt: string;
  mood: string;
  must_include: string[];
  user_message: string;
  missing: string[];
  issues: RawIssue[];
}

export interface AvatarAsset {
  uri: string;
  name: string;
  kind: "image" | "video";
  url: string;
  size: number;
}

export interface VoiceAsset {
  uri: string;
  name: string;
  language: string;
  sex: string;
  age_range: string;
  url: string;
}

export interface VoiceInfo {
  name: string;
  description: string;
  text: string;
  duration_s: number;
}

export interface GalleryItem {
  uri: string;
  title: string;
  channel_name: string;
  date: string | null;
  task_id: string | null;
  channel_id: string | null;
  channel_label: string | null;
  hashtags: string[];
  modified: string;
  video_url: string;
  download_url: string;
}

export interface RawIssue {
  loc?: (string | number)[];
  msg?: string;
}

/** Une erreur ou un avertissement rattaché à un champ : `key` est son chemin (`agent_config.brief.prompt`). */
export interface Issue {
  key: string;
  message: string;
}

export function toIssues(raw: RawIssue[] | undefined): Issue[] {
  return (raw ?? []).map((item) => ({
    key: (item.loc ?? []).filter((part, index) => !(index === 0 && part === "body")).join("."),
    message: (item.msg ?? "Valeur invalide").replace(/^Value error, /, ""),
  }));
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

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    const headers = init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" };
    response = await fetch(url, { headers, ...init });
  } catch {
    throw new ApiError("Serveur injoignable.", 0);
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (response.ok) return body as T;

  const detail = body?.detail;
  if (Array.isArray(detail)) {
    const issues = toIssues(detail as RawIssue[]);
    throw new ApiError(
      issues.length === 1 ? "1 champ à corriger." : `${issues.length} champs à corriger.`,
      response.status,
      issues,
    );
  }
  throw new ApiError(typeof detail === "string" ? detail : `Erreur ${response.status}`, response.status);
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export interface Saved {
  channel: Channel;
  warnings: RawIssue[];
}

export const api = {
  catalog: () => request<Catalog>("/api/catalog"),
  queue: () => request<{ pending: number; working: number }>("/api/queue"),

  channels: () => request<ChannelSummary[]>("/api/channels"),
  channel: (id: string) => request<Saved>(`/api/channels/${encodeURIComponent(id)}`),
  createChannel: (channel: ChannelData) => request<Saved>("/api/channels", json("POST", channel)),
  updateChannel: (channel: Channel) =>
    request<Saved>(`/api/channels/${encodeURIComponent(channel.id)}`, json("PUT", channel)),
  deleteChannel: (id: string, version: number) =>
    request<void>(`/api/channels/${encodeURIComponent(id)}?version=${version}`, { method: "DELETE" }),
  render: (channel: ChannelData, values: Record<string, string>) =>
    request<Preview>("/api/render", json("POST", { channel, values })),
  launch: (id: string, values: Record<string, string>, channelVersion: number) =>
    request<{ task_id: string; queue_position: number }>(
      `/api/channels/${encodeURIComponent(id)}/runs`,
      json("POST", { values, channel_version: channelVersion }),
    ),

  runs: (filters: { channel_id?: string; status?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) if (value) query.set(key, String(value));
    return request<RunSummary[]>(`/api/runs?${query}`);
  },
  run: (taskId: string) => request<RunDetail>(`/api/runs/${encodeURIComponent(taskId)}`),
  deleteRun: (taskId: string) => request<void>(`/api/runs/${encodeURIComponent(taskId)}`, { method: "DELETE" }),
  gallery: () => request<GalleryItem[]>("/api/gallery"),

  avatars: () => request<AvatarAsset[]>("/api/assets/avatars"),
  uploadAvatar: (file: File, name: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("name", name);
    return request<AvatarAsset>("/api/assets/avatars", { method: "POST", body: form });
  },
  voices: () => request<VoiceAsset[]>("/api/assets/voices"),
  voiceInfo: (uri: string) => request<VoiceInfo>(`/api/assets/voices/info?uri=${encodeURIComponent(uri)}`),
};
