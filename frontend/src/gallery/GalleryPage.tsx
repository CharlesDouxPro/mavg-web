// La galerie : les vidéos publiées, lues au survol, ouvertes en grand au clic.

import { useRef, useState } from "react";
import { api, type GalleryItem } from "../api";
import { usePolling } from "../lib/hooks";
import { ago } from "../lib/format";
import { go } from "../lib/router";
import { Icon } from "../ui/Icon";
import { Empty, Notice, Segmented } from "../ui/kit";

export function GalleryPage() {
  // Les liens signés valent une heure : on les renouvelle bien avant.
  const gallery = usePolling(() => api.gallery(), [], () => 45 * 60_000);
  const [folder, setFolder] = useState("all");
  const [open, setOpen] = useState<GalleryItem | null>(null);
  const folders = [...new Set((gallery.data ?? []).map((item) => item.channel_name))].sort();
  const shown = (gallery.data ?? []).filter((item) => folder === "all" || item.channel_name === folder);

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Galerie</h1>
          <p className="page-sub">Toutes les vidéos publiées dans le bucket, les plus récentes d'abord.</p>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={gallery.refresh}>
            <Icon name="refresh" /> Actualiser
          </button>
        </div>
      </header>

      {folders.length > 1 && (
        <div className="filters">
          <Segmented
            value={folder}
            onChange={setFolder}
            options={[{ value: "all", label: "Tout" }, ...folders.map((name) => ({ value: name, label: name }))]}
          />
        </div>
      )}

      {gallery.error && <Notice tone="error">{gallery.error.message}</Notice>}
      {!gallery.data && !gallery.error && (
        <div className="gallery">
          {Array.from({ length: 8 }, (_, i) => <div key={i} className="skeleton" style={{ aspectRatio: "9 / 19" }} />)}
        </div>
      )}
      {gallery.data?.length === 0 && (
        <div className="card">
          <Empty icon="film" title="Pas encore de vidéo">
            <p>Les vidéos apparaissent ici dès que le worker les publie.</p>
          </Empty>
        </div>
      )}

      <div className="gallery">
        {shown.map((item) => (
          <VideoCard key={item.uri} item={item} onOpen={() => (item.task_id ? go({ page: "runs", id: item.task_id }) : setOpen(item))} />
        ))}
      </div>

      {open && (
        <>
          <div className="backdrop" onClick={() => setOpen(null)} />
          <div className="lightbox" onClick={() => setOpen(null)}>
            <div className="lightbox-inner" onClick={(e) => e.stopPropagation()}>
              <video src={open.video_url} controls autoPlay playsInline />
              <div className="row">
                <strong>{open.title}</strong>
                <span className="muted small">· {open.channel_name} · {open.date}</span>
                <a className="btn sm" href={open.download_url}>
                  <Icon name="download" /> Télécharger
                </a>
                <button className="btn sm ghost icon" onClick={() => setOpen(null)} aria-label="Fermer">
                  <Icon name="x" />
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function VideoCard({ item, onOpen }: { item: GalleryItem; onOpen: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  return (
    <button
      className="video-card"
      onClick={onOpen}
      onMouseEnter={() => video.current?.play().catch(() => undefined)}
      onMouseLeave={() => {
        if (!video.current) return;
        video.current.pause();
        video.current.currentTime = 0.1;
      }}
    >
      <div className="video-frame">
        <video ref={video} src={`${item.video_url}#t=0.1`} muted loop playsInline preload="metadata" />
        <span className="play-hint">
          <Icon name="play" size={30} />
        </span>
      </div>
      <div className="video-info">
        <div className="title">{item.title}</div>
        <div className="muted small row" style={{ marginTop: 4, gap: 6 }}>
          <span className="mono truncate">{item.channel_label ?? item.channel_name}</span>
          <span className="faint">· {ago(item.modified)}</span>
        </div>
      </div>
    </button>
  );
}
