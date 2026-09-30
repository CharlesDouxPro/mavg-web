// L'état partagé par toutes les pages : catalogue, liste des channels, file, lancement de run.

import { createContext, useContext } from "react";
import type { Catalog, ChannelSummary } from "./api";

export interface LaunchRequest {
  channelId?: string;
  values?: Record<string, string>;
}

export interface Studio {
  catalog: Catalog;
  channels: ChannelSummary[] | null;
  reloadChannels: () => void;
  queue: { pending: number; working: number } | null;
  refreshQueue: () => void;
  launch: (request?: LaunchRequest) => void;
  runsVersion: number;
}

export const StudioContext = createContext<Studio | null>(null);

export function useStudio(): Studio {
  const studio = useContext(StudioContext);
  if (!studio) throw new Error("useStudio hors de StudioContext");
  return studio;
}
