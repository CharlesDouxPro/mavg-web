// La page Channels : la liste à gauche, l'éditeur à droite.

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, toIssues, type Catalog, type Channel, type ChannelData, type Issue } from "../api";
import { clone } from "../lib/data";
import { flag } from "../lib/format";
import { go, href } from "../lib/router";
import { useStudio } from "../studio";
import { Icon, Spinner } from "../ui/Icon";
import { Empty, Media, Notice } from "../ui/kit";
import { ChannelEditor, toData } from "./ChannelEditor";

function blank(catalog: Catalog): ChannelData {
  return {
    id: "",
    name: "",
    description: "",
    channel_config: { channel_name: "", email: "" },
    parameters: [],
    agent_config: clone(catalog.defaults.agent_config),
  };
}

export function ChannelsPage({ selected }: { selected?: string }) {
  const { channels, reloadChannels, catalog } = useStudio();
  const [query, setQuery] = useState("");
  const [loaded, setLoaded] = useState<{ channel: Channel; warnings: Issue[] } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [seed, setSeed] = useState<ChannelData | null>(null);
  const dirty = useRef(false);
  const onDirty = useCallback((value: boolean) => {
    dirty.current = value;
  }, []);

  useEffect(() => {
    if (!selected && channels?.length) window.location.replace(href({ page: "channels", id: channels[0].id }));
  }, [selected, channels]);

  useEffect(() => {
    setLoadError(null);
    if (!selected || selected === "new") return setLoaded(null);
    if (loaded?.channel.id === selected) return;
    setLoaded(null);
    api
      .channel(selected)
      .then((result) => setLoaded({ channel: result.channel, warnings: toIssues(result.warnings) }))
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : String(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const open = (id: string) => {
    if (dirty.current && !window.confirm("Des modifications ne sont pas enregistrées. Les abandonner ?")) return;
    dirty.current = false;
    go({ page: "channels", id });
  };
  const create = (from?: ChannelData) => {
    if (dirty.current && !window.confirm("Des modifications ne sont pas enregistrées. Les abandonner ?")) return;
    dirty.current = false;
    setSeed(from ?? blank(catalog));
    go({ page: "channels", id: "new" });
  };

  const shown = (channels ?? []).filter((channel) =>
    `${channel.name} ${channel.channel_name} ${channel.id}`.toLowerCase().includes(query.toLowerCase()),
  );
  const summary = channels?.find((channel) => channel.id === selected);

  return (
    <div className="page">
      <div className="split">
        <div className="channel-list">
          <div className="row">
            <div className="search grow">
              <Icon name="search" />
              <input className="input" placeholder="Rechercher un channel" value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
            <button className="btn icon solid" title="Nouveau channel" onClick={() => create()}>
              <Icon name="plus" />
            </button>
          </div>
          {!channels && Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton" style={{ height: 62 }} />)}
          {channels?.length === 0 && (
            <p className="muted small" style={{ padding: "8px 4px" }}>
              Aucun channel pour l'instant.
            </p>
          )}
          {selected === "new" && (
            <button className="channel-item active">
              <span className="thumb s"><Icon name="plus" /></span>
              <span className="grow">
                <div className="name">{seed?.name || "Nouveau channel"}</div>
                <div className="meta">Brouillon</div>
              </span>
            </button>
          )}
          {shown.map((channel) => (
            <button
              key={channel.id}
              className={`channel-item${channel.id === selected ? " active" : ""}`}
              onClick={() => open(channel.id)}
            >
              <Media url={channel.avatar?.url} kind={channel.avatar?.kind ?? "image"} />
              <span className="grow" style={{ minWidth: 0 }}>
                <div className="name truncate">{channel.name}</div>
                <div className="meta">
                  {channel.language && <span>{flag(channel.language)}</span>}
                  <span className="truncate">{channel.channel_name}</span>
                  {channel.last_run && <span className={`badge ${channel.last_run.status}`} style={{ height: 18, padding: "0 6px" }}><span className="dot" /></span>}
                </div>
              </span>
              {channel.runs > 0 && <span className="faint small">{channel.runs}</span>}
            </button>
          ))}
        </div>

        <div style={{ minWidth: 0 }}>
          {channels?.length === 0 && selected !== "new" && (
            <div className="card">
              <Empty icon="layers" title="Crée ton premier channel">
                <p>
                  Un channel est une config de base : un brief, un avatar, une voix et des paramètres. Tu lanceras ensuite
                  autant de runs que tu veux depuis lui.
                </p>
                <button className="btn primary" onClick={() => create()}>
                  <Icon name="plus" />
                  Nouveau channel
                </button>
              </Empty>
            </div>
          )}
          {loadError && <Notice tone="error">{loadError}</Notice>}
          {selected && selected !== "new" && !loaded && !loadError && (
            <div className="empty">
              <Spinner size={20} />
            </div>
          )}
          {selected === "new" && (
            <ChannelEditor
              key="new"
              saved={null}
              initial={seed ?? blank(catalog)}
              initialWarnings={[]}
              onDirty={onDirty}
              onSaved={(channel) => {
                dirty.current = false;
                setLoaded({ channel, warnings: [] });
                reloadChannels();
                go({ page: "channels", id: channel.id });
              }}
              onDeleted={() => undefined}
              onDuplicate={() => undefined}
            />
          )}
          {loaded && selected === loaded.channel.id && (
            <ChannelEditor
              key={loaded.channel.id}
              saved={loaded.channel}
              initial={toData(loaded.channel)}
              initialWarnings={loaded.warnings}
              lastRun={summary?.last_run}
              onDirty={onDirty}
              onSaved={(channel) => {
                setLoaded({ channel, warnings: [] });
                reloadChannels();
              }}
              onDeleted={() => {
                dirty.current = false;
                setLoaded(null);
                reloadChannels();
                go({ page: "channels" });
              }}
              onDuplicate={(draft) =>
                create({
                  ...clone(draft),
                  id: `${draft.id}-copie`.slice(0, 40),
                  name: `${draft.name} (copie)`,
                })
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}
