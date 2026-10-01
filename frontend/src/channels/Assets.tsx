// Choisir l'avatar, les images de référence et la voix dans le bucket : aperçu, import, écoute.

import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, type AvatarAsset, type VoiceAsset, type VoiceInfo } from "../api";
import { LANGUAGE_FR, SEX_LABEL, flag } from "../lib/format";
import { Icon, Spinner } from "../ui/Icon";
import { Media, Notice, Segmented } from "../ui/kit";
import { useToast } from "../ui/overlay";

/** Un dossier du bucket qu'on parcourt et où l'on importe. */
interface Library {
  list: () => Promise<AvatarAsset[]>;
  upload: (file: File, name: string) => Promise<AvatarAsset>;
  accept: string;
  hint: string;
  imported: string;
  unavailable: string;
}

const AVATARS: Library = {
  list: api.avatars,
  upload: api.uploadAvatar,
  accept: "image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm",
  hint: "image ou vidéo",
  imported: "Avatar importé",
  unavailable: "Avatars indisponibles",
};

const REFERENCES: Library = {
  list: api.references,
  upload: api.uploadReference,
  accept: "image/png,image/jpeg,image/webp",
  hint: "PNG, JPEG, WebP",
  imported: "Image importée",
  unavailable: "Images indisponibles",
};

interface PickerProps {
  value: string;
  onPick: (asset: AvatarAsset) => void;
  suggestedName: string;
}

export const AvatarPicker = (props: PickerProps) => <MediaPicker library={AVATARS} {...props} />;

/** Les images de `references/` : un personnage s'y retrouve d'un épisode à l'autre. */
export const ReferencePicker = (props: PickerProps) => <MediaPicker library={REFERENCES} {...props} />;

function MediaPicker({ library, value, onPick, suggestedName }: PickerProps & { library: Library }) {
  const [items, setItems] = useState<AvatarAsset[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const toast = useToast();

  const load = () =>
    library
      .list()
      .then(setItems)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
  useEffect(() => {
    load();
  }, []);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      const item = await library.upload(file, suggestedName || file.name.replace(/\.[^.]+$/, ""));
      setItems((current) => [item, ...(current ?? [])]);
      onPick(item);
      toast("ok", library.imported, item.uri.replace(/^s3:\/\/[^/]+\//, ""));
    } catch (err) {
      toast("error", "Import impossible", err instanceof ApiError ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  };

  if (error) return <Notice tone="warn">{library.unavailable} : {error}</Notice>;
  return (
    <div className="asset-grid">
      <button
        type="button"
        className={`dropzone${over ? " over" : ""}`}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          upload(e.dataTransfer.files[0]);
        }}
      >
        {uploading ? <Spinner size={20} /> : <Icon name="upload" size={20} />}
        <span>{uploading ? "Import…" : "Importer"}</span>
        <span className="faint" style={{ fontSize: 11 }}>{library.hint}</span>
      </button>
      <input
        ref={input}
        type="file"
        hidden
        accept={library.accept}
        onChange={(e) => {
          upload(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      {!items &&
        Array.from({ length: 5 }, (_, i) => <div key={i} className="skeleton" style={{ aspectRatio: "9 / 14" }} />)}
      {items?.map((item) => (
        <button
          key={item.uri}
          type="button"
          className={`asset${item.uri === value ? " selected" : ""}`}
          onClick={() => onPick(item)}
          title={item.uri}
        >
          {item.kind === "video" ? (
            <video src={`${item.url}#t=0.5`} muted playsInline preload="metadata" />
          ) : (
            <img src={item.url} alt="" loading="lazy" />
          )}
          <span className="asset-name truncate">{item.name}</span>
          {item.uri === value && (
            <span className="asset-check">
              <Icon name="check" size={12} />
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

let referenceList: Promise<AvatarAsset[]> | null = null;

/** La valeur d'un paramètre image : la vignette choisie, et la bibliothèque pour en changer. */
export function ImageValueInput({ value, onChange }: { value: string; onChange: (next: string) => void }) {
  const [open, setOpen] = useState(false);
  const [known, setKnown] = useState<Record<string, string>>({});
  const [url, setUrl] = useState<string | null>(null);

  // Une valeur reçue toute faite (défaut, « Relancer… ») : son lien signé vient du listing.
  useEffect(() => {
    if (!value) return setUrl(null);
    if (known[value]) return setUrl(known[value]);
    referenceList ??= api.references().catch(() => []);
    let cancelled = false;
    referenceList.then((list) => !cancelled && setUrl(list.find((image) => image.uri === value)?.url ?? null));
    return () => {
      cancelled = true;
    };
  }, [value, known]);

  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row">
        <Media url={url} kind="image" />
        <span className={`grow truncate small${value ? " mono" : " faint"}`} title={value || undefined}>
          {value ? value.split("/").pop() : "Aucune image"}
        </span>
        <button type="button" className="btn sm" onClick={() => setOpen(!open)}>
          <Icon name={open ? "x" : "upload"} size={13} />
          {open ? "Fermer" : value ? "Changer" : "Choisir"}
        </button>
        {value && (
          <button type="button" className="btn ghost sm icon" onClick={() => onChange("")} aria-label="Retirer l'image">
            <Icon name="trash" size={13} />
          </button>
        )}
      </div>
      {open && (
        <ReferencePicker
          value={value}
          suggestedName=""
          onPick={(image) => {
            setKnown((current) => ({ ...current, [image.uri]: image.url }));
            referenceList = null;
            onChange(image.uri);
            setOpen(false);
          }}
        />
      )}
    </div>
  );
}

type Sex = "all" | "female" | "male";

export function VoicePicker({
  value,
  language,
  onPick,
}: {
  value: string;
  language: string;
  onPick: (uri: string) => void;
}) {
  const [voices, setVoices] = useState<VoiceAsset[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState(language || "all");
  const [sex, setSex] = useState<Sex>("all");
  const [age, setAge] = useState("all");
  const [playing, setPlaying] = useState<string | null>(null);
  const [info, setInfo] = useState<VoiceInfo | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    api
      .voices()
      .then(setVoices)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
    return () => audio.current?.pause();
  }, []);
  useEffect(() => setLang(language || "all"), [language]);
  useEffect(() => {
    setInfo(null);
    if (value) api.voiceInfo(value).then(setInfo).catch(() => setInfo(null));
  }, [value]);

  const languages = useMemo(() => [...new Set((voices ?? []).map((v) => v.language))].sort(), [voices]);
  const ages = useMemo(() => [...new Set((voices ?? []).map((v) => v.age_range))].sort(), [voices]);
  const shown = (voices ?? []).filter(
    (v) => (lang === "all" || v.language === lang) && (sex === "all" || v.sex === sex) && (age === "all" || v.age_range === age),
  );
  const selected = voices?.find((v) => v.uri === value);

  const toggle = (voice: VoiceAsset) => {
    if (playing === voice.uri) {
      audio.current?.pause();
      setPlaying(null);
      return;
    }
    audio.current?.pause();
    const element = new Audio(voice.url);
    element.onended = () => setPlaying(null);
    element.play().catch(() => setPlaying(null));
    audio.current = element;
    setPlaying(voice.uri);
  };

  if (error) return <Notice tone="warn">Voix indisponibles : {error}</Notice>;
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="row wrap">
        <select className="input" style={{ width: 170 }} value={lang} onChange={(e) => setLang(e.target.value)}>
          <option value="all">Toutes les langues</option>
          {languages.map((code) => (
            <option key={code} value={code}>
              {flag(code)} {LANGUAGE_FR[code] ?? code}
            </option>
          ))}
        </select>
        <Segmented<Sex>
          value={sex}
          onChange={setSex}
          options={[
            { value: "all", label: "Tous" },
            { value: "female", label: "Femme" },
            { value: "male", label: "Homme" },
          ]}
        />
        <select className="input" style={{ width: 130 }} value={age} onChange={(e) => setAge(e.target.value)}>
          <option value="all">Tous âges</option>
          {ages.map((range) => (
            <option key={range} value={range}>
              {range} ans
            </option>
          ))}
        </select>
        <span className="faint small">{voices ? `${shown.length} voix` : ""}</span>
      </div>

      <div className="voice-list">
        <button type="button" className={`voice${!value ? " selected" : ""}`} onClick={() => onPick("")}>
          <span className="play" style={{ background: "var(--surface-3)" }}>
            <Icon name="x" size={13} />
          </span>
          <span className="grow">
            <div className="voice-name">Aucune</div>
            <div className="voice-meta">Le modèle invente la voix</div>
          </span>
        </button>
        {!voices && Array.from({ length: 6 }, (_, i) => <div key={i} className="skeleton" style={{ height: 48 }} />)}
        {shown.map((voice) => (
          <div
            key={voice.uri}
            role="button"
            tabIndex={0}
            className={`voice${voice.uri === value ? " selected" : ""}`}
            onClick={() => onPick(voice.uri)}
            onKeyDown={(e) => e.key === "Enter" && onPick(voice.uri)}
          >
            <button
              type="button"
              className={`play${playing === voice.uri ? " on" : ""}`}
              onClick={(e) => {
                e.stopPropagation();
                toggle(voice);
              }}
              aria-label={`Écouter ${voice.name}`}
            >
              {playing === voice.uri ? (
                <span className="wave"><i /><i /><i /><i /></span>
              ) : (
                <Icon name="play" size={12} />
              )}
            </button>
            <span className="grow" style={{ minWidth: 0 }}>
              <div className="voice-name truncate">{voice.name}</div>
              <div className="voice-meta">
                {flag(voice.language)} {SEX_LABEL[voice.sex] ?? voice.sex} · {voice.age_range}
              </div>
            </span>
            {voice.uri === value && <Icon name="check" size={14} />}
          </div>
        ))}
      </div>

      {selected && (
        <div className="notice info">
          <Icon name="mic" />
          <div className="grow">
            <strong style={{ textTransform: "capitalize" }}>{selected.name}</strong>
            <span className="muted"> · {LANGUAGE_FR[selected.language] ?? selected.language}, {SEX_LABEL[selected.sex]?.toLowerCase()}, {selected.age_range} ans</span>
            {info?.description && <p style={{ margin: "6px 0 0" }}>{info.description}</p>}
            {info?.text && <p className="muted" style={{ margin: "6px 0 0", fontStyle: "italic" }}>« {info.text} »</p>}
          </div>
        </div>
      )}
      {value && !selected && voices && (
        <Notice tone="warn">
          La voix <code>{value}</code> n'est pas dans le catalogue <code>voices/</code>.
        </Notice>
      )}
    </div>
  );
}
