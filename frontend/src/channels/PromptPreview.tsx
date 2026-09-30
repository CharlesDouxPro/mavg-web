// Ce que l'agent recevra : le message rendu par le serveur, valeurs surlignées.

import { useEffect, useState } from "react";
import { ApiError, api, type ChannelData, type Preview } from "../api";
import { highlight } from "../lib/data";
import { useDebounced } from "../lib/hooks";
import { Icon, Spinner } from "../ui/Icon";

export function PromptPreview({
  channel,
  values = {},
  compact,
}: {
  channel: ChannelData;
  values?: Record<string, string>;
  compact?: boolean;
}) {
  const request = useDebounced(JSON.stringify({ channel, values }), 450);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const { channel, values } = JSON.parse(request) as { channel: ChannelData; values: Record<string, string> };
    setLoading(true);
    api
      .render(channel, values)
      .then((next) => {
        if (cancelled) return;
        setPreview(next);
        setError(null);
      })
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : String(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [request]);

  const filled = Object.values(values).filter(Boolean);
  const defaults = channel.parameters.map((parameter) => parameter.default).filter(Boolean);
  const segments = preview ? highlight(preview.user_message, [...filled, ...defaults]) : [];
  const unresolved = new Set(segments.filter((segment) => segment.kind === "missing").map((segment) => segment.text)).size;

  return (
    <div>
      <div className="preview-head">
        <Icon name="sparkles" size={14} />
        <strong className="small">Ce que l'agent reçoit</strong>
        {loading && <Spinner size={13} />}
        {preview && unresolved > 0 && (
          <span className="badge failed" style={{ marginLeft: "auto" }}>
            {unresolved} sans valeur
          </span>
        )}
        {preview && unresolved === 0 && (
          <span className="badge done" style={{ marginLeft: "auto" }}>
            <Icon name="check" size={11} />
            complet
          </span>
        )}
      </div>
      <div className="preview-box" style={compact ? { maxHeight: 300 } : undefined}>
        {error && <p className="field-msg error">{error}</p>}
        {!preview && !error && <div className="skeleton" style={{ height: 120 }} />}
        {preview && (
          <pre className="preview">
            {segments.map((segment, index) =>
              segment.kind === "text" ? (
                segment.text
              ) : (
                <span key={index} className={segment.kind === "value" ? "val" : "miss"}>
                  {segment.text}
                </span>
              ),
            )}
          </pre>
        )}
      </div>
      {preview && preview.must_include.length > 0 && (
        <p className="field-help" style={{ marginTop: 8 }}>
          La description devra contenir : {preview.must_include.map((item) => `« ${item} »`).join(", ")}.
        </p>
      )}
    </div>
  );
}
