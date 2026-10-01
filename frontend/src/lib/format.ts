// Dates relatives, durées, drapeaux et libellés.

const rtf = new Intl.RelativeTimeFormat("fr", { numeric: "auto" });
const full = new Intl.DateTimeFormat("fr", { dateStyle: "medium", timeStyle: "short" });

export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000;
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["second", 60], ["minute", 60], ["hour", 24], ["day", 30], ["month", 12], ["year", Infinity],
  ];
  let value = seconds;
  for (const [unit, size] of steps) {
    if (Math.abs(value) < size) return rtf.format(Math.round(value), unit);
    value /= size;
  }
  return full.format(new Date(iso));
}

export const fullDate = (iso: string | null | undefined) => (iso ? full.format(new Date(iso)) : "—");

/** Une valeur de run lisible : une image du bucket se lit à son nom de fichier. */
export const shortValue = (value: string) => (value.startsWith("s3://") ? value.split("/").pop() ?? value : value);

export function duration(from: string | null | undefined, to?: string | null): string {
  if (!from) return "";
  const seconds = Math.max(0, ((to ? new Date(to) : new Date()).getTime() - new Date(from).getTime()) / 1000);
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ${String(Math.round(seconds % 60)).padStart(2, "0")}`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`;
}

const FLAGS: Record<string, string> = {
  fr: "🇫🇷", en: "🇬🇧", es: "🇪🇸", de: "🇩🇪", it: "🇮🇹", pt: "🇵🇹", nl: "🇳🇱", pl: "🇵🇱",
  ru: "🇷🇺", tr: "🇹🇷", sv: "🇸🇪", ar: "🇸🇦", ja: "🇯🇵", ko: "🇰🇷", zh: "🇨🇳", hi: "🇮🇳",
};
export const flag = (code: string) => FLAGS[code] ?? "🌐";

export const LANGUAGE_FR: Record<string, string> = {
  fr: "Français", en: "Anglais", es: "Espagnol", de: "Allemand", it: "Italien", pt: "Portugais",
  nl: "Néerlandais", pl: "Polonais", ru: "Russe", tr: "Turc", sv: "Suédois", ar: "Arabe",
  ja: "Japonais", ko: "Coréen", zh: "Chinois", hi: "Hindi",
};

export const STATUS_LABEL: Record<string, string> = {
  pending: "En attente",
  working: "En cours",
  done: "Terminé",
  failed: "Échec",
};

export const SEX_LABEL: Record<string, string> = { female: "Femme", male: "Homme" };

export function slugify(text: string): string {
  return text
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

export async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
