import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api, type Catalog } from "./api";
import { ChannelsPage } from "./channels/ChannelsPage";
import { GalleryPage } from "./gallery/GalleryPage";
import { usePolling } from "./lib/hooks";
import { href, useRoute, type Route } from "./lib/router";
import { LaunchDrawer } from "./runs/LaunchDrawer";
import { RunsPage } from "./runs/RunsPage";
import { StudioContext, type LaunchRequest, type Studio } from "./studio";
import { Icon, Spinner, type IconName } from "./ui/Icon";
import { ToastProvider } from "./ui/overlay";

const NAV: { page: Route["page"]; label: string; icon: IconName }[] = [
  { page: "channels", label: "Channels", icon: "layers" },
  { page: "runs", label: "Runs", icon: "list" },
  { page: "gallery", label: "Galerie", icon: "grid" },
];

export function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .catalog()
      .then(setCatalog)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
  }, []);

  if (error)
    return (
      <div className="splash">
        <div className="empty-icon"><Icon name="alert" size={24} /></div>
        <div>
          <strong>Impossible de joindre l'API</strong>
          <p>{error}</p>
        </div>
      </div>
    );
  if (!catalog)
    return (
      <div className="splash">
        <Spinner size={22} />
        Chargement du studio…
      </div>
    );
  return (
    <ToastProvider>
      <Shell catalog={catalog} />
    </ToastProvider>
  );
}

function Shell({ catalog }: { catalog: Catalog }) {
  const route = useRoute();
  const [launchRequest, setLaunchRequest] = useState<LaunchRequest | null>(null);
  const [runsVersion, setRunsVersion] = useState(0);

  const channels = usePolling(() => api.channels(), [], () => 30_000);
  const queue = usePolling(() => api.queue(), [], (data) => (data && data.pending + data.working > 0 ? 4000 : 15_000));

  const launch = useCallback((request: LaunchRequest = {}) => setLaunchRequest(request), []);
  useEffect(() => setLaunchRequest(null), [route.page]);
  const studio: Studio = useMemo(
    () => ({
      catalog,
      channels: channels.data,
      reloadChannels: channels.refresh,
      queue: queue.data,
      refreshQueue: queue.refresh,
      launch,
      runsVersion,
    }),
    [catalog, channels.data, channels.refresh, queue.data, queue.refresh, launch, runsVersion],
  );

  const active = queue.data?.working ?? 0;
  const pending = queue.data?.pending ?? 0;

  return (
    <StudioContext.Provider value={studio}>
      <div className="app">
        <nav className="sidebar">
          <div className="brand">
            <div className="brand-mark"><Icon name="play" size={15} /></div>
            <div>
              <div className="brand-name">MAVG Studio</div>
              <div className="brand-sub">Vidéos verticales</div>
            </div>
          </div>
          {NAV.map((item) => (
            <a
              key={item.page}
              href={href({ page: item.page } as Route)}
              className={`nav-item${route.page === item.page ? " active" : ""}`}
            >
              <Icon name={item.icon} />
              {item.label}
              {item.page === "channels" && channels.data && <span className="nav-count">{channels.data.length}</span>}
              {item.page === "runs" && pending + active > 0 && (
                <span className="nav-count live">{pending + active}</span>
              )}
            </a>
          ))}
          <button className="btn primary" style={{ marginTop: 14 }} onClick={() => launch()}>
            <Icon name="rocket" />
            Nouveau run
          </button>
          <div className="sidebar-foot">
            <div className="queue-card">
              <strong>File du worker</strong>
              <div className="queue-row">
                <span className={`badge ${active ? "working" : "outline"}`}>
                  <span className="dot" />
                  {active} en cours
                </span>
                <span className={`badge ${pending ? "pending" : "outline"}`}>{pending} en attente</span>
              </div>
              {pending > 0 && active === 0 && (
                <p className="small" style={{ margin: "8px 0 0" }}>
                  Aucun rendu en cours : les runs partiront au démarrage de l'instance GPU.
                </p>
              )}
            </div>
          </div>
        </nav>

        <main className="main">
          {route.page === "channels" && <ChannelsPage selected={route.id} />}
          {route.page === "runs" && <RunsPage selected={route.id} />}
          {route.page === "gallery" && <GalleryPage />}
        </main>
      </div>

      <LaunchDrawer
        request={launchRequest}
        onClose={() => setLaunchRequest(null)}
        onLaunched={() => {
          setRunsVersion((value) => value + 1);
          queue.refresh();
          channels.refresh();
        }}
      />
    </StudioContext.Provider>
  );
}
