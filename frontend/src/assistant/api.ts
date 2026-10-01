// Le contrat avec l'API de l'assistant (app/routers/assistant.py).

import { ApiError, toIssues, type ChannelData, type RawIssue } from "../api";

export type CardStatus = "open" | "done" | "failed" | "cancelled";

export interface MediaView {
  uri: string;
  url: string | null;
  kind: "image" | "video";
}

export interface VoiceView {
  uri: string;
  name: string;
  language?: string;
  sex?: string;
  age_range?: string;
  url?: string;
  description?: string;
  text?: string;
  missing?: boolean;
}

interface CardBase {
  id: string;
  status: CardStatus;
  error: string | null;
}

export interface ImageCard extends CardBase {
  kind: "image";
  payload: { purpose: "avatar" | "reference"; name: string; prompt: string; why: string };
  result: { uri?: string; media?: MediaView | null };
}

export interface VoicesCard extends CardBase {
  kind: "voices";
  payload: { uris: string[]; why: string };
  result: { uri?: string };
  voices: VoiceView[];
}

export interface ChannelCard extends CardBase {
  kind: "channel";
  payload: { channel: ChannelData; base_version: number | null; advice: string[] };
  result: { channel_id?: string; version?: number; warnings?: string[] };
  avatar: MediaView | null;
  voice: VoiceView | null;
}

export interface RunCandidate {
  n: number;
  pitch: string;
  values: Record<string, string>;
}

export interface RunResult {
  n: number;
  task_id?: string;
  queue_position?: number;
  error?: string;
}

export interface RunsCard extends CardBase {
  kind: "runs";
  payload: { channel_id: string; channel_name: string; channel_version: number; candidates: RunCandidate[] };
  result: { runs?: RunResult[] };
}

export type Card = ImageCard | VoicesCard | ChannelCard | RunsCard;

export type Item = { kind: "user" | "assistant" | "note"; text: string } | { kind: "card"; card: Card };

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  base_version: number | null;
  draft: ChannelData | null;
  draft_media: { avatar: MediaView | null; voice: VoiceView | null };
  references: { name: string; uri: string; url: string | null }[];
  items: Item[];
  busy: boolean;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  channel_id: string | null;
  channel_name: string | null;
}

export interface CardAction {
  action: "attach" | "choose" | "confirm" | "cancel";
  uri?: string;
  selected?: number[];
}

// Même traitement des erreurs que `request` dans ../api.ts, qui n'est pas exporté.
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
    const issues = toIssues(detail as RawIssue[]);
    throw new ApiError(issues.map((issue) => issue.message).join(" "), response.status, issues);
  }
  throw new ApiError(typeof detail === "string" ? detail : `Erreur ${response.status}`, response.status);
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
const path = (id: string) => `/api/assistant/sessions/${encodeURIComponent(id)}`;

export const assistantApi = {
  list: () => request<ConversationSummary[]>("/api/assistant/sessions"),
  start: (channelId?: string) => request<Conversation>("/api/assistant/sessions", post({ channel_id: channelId ?? null })),
  get: (id: string) => request<Conversation>(path(id)),
  /** `text` vide : relance le tour resté sans réponse. */
  send: (id: string, text: string) => request<Conversation>(`${path(id)}/messages`, post({ text })),
  act: (id: string, cardId: string, action: CardAction) =>
    request<Conversation>(`${path(id)}/cards/${encodeURIComponent(cardId)}`, post(action)),
};
