// Choisir l'avatar et la voix dans le bucket : aperçu, import d'avatar, écoute des voix.

import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, type AvatarAsset, type VoiceAsset, type VoiceInfo } from "../api";
import { LANGUAGE_FR, SEX_LABEL, flag } from "../lib/format";
import { Icon, Spinner } from "../ui/Icon";
import { Notice, Segmented } from "../ui/kit";
import { useToast } from "../ui/overlay";

export function AvatarPicker({
  value,
  onPick,
  suggestedName,
}: {
  value: string;
  onPick: (avatar: AvatarAsset) => void;
  suggestedName: string;
}) {
  const [avatars, setAvatars] = useState<AvatarAsset[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const toast = useToast();

  const load = () =>
    api
      .avatars()
      .then(setAvatars)
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
  useEffect(() => {
    load();
  }, []);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      const avatar = await api.uploadAvatar(file, suggestedName || file.name.replace(/\.[^.]+$/, ""));
      setAvatars((current) => [avatar, ...(current ?? [])]);
      onPick(avatar);
      toast("ok", "Avatar importé", avatar.uri.replace(/^s3:\/\/[^/]+\//, ""));
    } catch (err) {
      toast("error", "Import impossible", err instanceof ApiError ? err.message : String(err));
    } finally {
      setUploading(false);
    }
  };

  if (error) return <Notice tone="warn">Avatars indisponibles : {error}</Notice>;
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
        <span className="faint" style={{ fontSize: 11 }}>image ou vidéo</span>
      </button>
      <input
        ref={input}
        type="file"
        hidden
        accept="image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm"
        onChange={(e) => {
          upload(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      {!avatars &&
        Array.from({ length: 5 }, (_, i) => <div key={i} className="skeleton" style={{ aspectRatio: "9 / 14" }} />)}
      {avatars?.map((avatar) => (
        <button
          key={avatar.uri}
          type="button"
          className={`asset${avatar.uri === value ? " selected" : ""}`}
          onClick={() => onPick(avatar)}
          title={avatar.uri}
        >
          {avatar.kind === "video" ? (
            <video src={`${avatar.url}#t=0.5`} muted playsInline preload="metadata" />
          ) : (
            <img src={avatar.url} alt="" loading="lazy" />
          )}
          <span className="asset-name truncate">{avatar.name}</span>
          {avatar.uri === value && (
            <span className="asset-check">
              <Icon name="check" size={12} />
            </span>
          )}
        </button>
      ))}
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
