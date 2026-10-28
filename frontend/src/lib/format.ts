import type { Cluster, EstimatedDimensionsCm } from '../api';

const HOUR = 3_600_000;

export function parseIso(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "just now", "12 min ago", "3 h ago", "6 d ago", "2 mo ago" */
export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
  const d = parseIso(iso);
  if (!d) return '';
  const diff = now.getTime() - d.getTime();
  const future = diff < 0;
  const abs = Math.abs(diff);
  const min = Math.round(abs / 60_000);
  let s: string;
  if (min < 1) return 'just now';
  if (min < 60) s = `${min} min`;
  else if (abs < 48 * HOUR) s = `${Math.round(abs / HOUR)} h`;
  else if (abs < 60 * 24 * HOUR) s = `${Math.round(abs / (24 * HOUR))} d`;
  else s = `${Math.round(abs / (30 * 24 * HOUR))} mo`;
  return future ? `in ${s}` : `${s} ago`;
}

/** India Standard Time is UTC+05:30 all year (no daylight saving). */
const IST_OFFSET_MS = 330 * 60_000;

const pad2 = (n: number): string => String(n).padStart(2, '0');

/** ISO-style date in India Standard Time: "2026-10-28 14:30" (24 h), or "2026-10-28" with `{ time: false }`. */
export function fmtDate(iso: string | null | undefined, opts: { time?: boolean } = { time: true }): string {
  const d = parseIso(iso);
  if (!d) return '—';
  const ist = new Date(d.getTime() + IST_OFFSET_MS); // read back with the UTC getters
  const date = `${ist.getUTCFullYear()}-${pad2(ist.getUTCMonth() + 1)}-${pad2(ist.getUTCDate())}`;
  return opts.time ? `${date} ${pad2(ist.getUTCHours())}:${pad2(ist.getUTCMinutes())}` : date;
}

/** Hours → "5.5 h" or "3.1 d". */
export function fmtHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || Number.isNaN(hours)) return '—';
  const h = Math.abs(hours);
  if (h < 1) return `${Math.round(h * 60)} min`;
  if (h < 48) return `${Math.round(h * 10) / 10} h`;
  return `${Math.round((h / 24) * 10) / 10} d`;
}

export function slaText(c: Pick<Cluster, 'sla_breached' | 'hours_to_sla' | 'status'>): string {
  if (c.status === 'resolved_verified') return 'Closed';
  if (c.sla_breached || c.hours_to_sla < 0) return `SLA breached by ${fmtHours(-c.hours_to_sla)}`;
  return `SLA due in ${fmtHours(c.hours_to_sla)}`;
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${v.toFixed(digits)}%`;
}

export function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toFixed(digits);
}

/** "two_wheeler_skid_risk" → "Two wheeler skid risk" */
export function humanize(s: string | null | undefined): string {
  if (!s) return '';
  const t = s.replace(/[_-]+/g, ' ').trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

const LANGUAGES: Record<string, string> = {
  kn: 'Kannada',
  en: 'English',
  hi: 'Hindi',
  ta: 'Tamil',
  te: 'Telugu',
  ml: 'Malayalam',
  ur: 'Urdu',
  mr: 'Marathi',
  'kn-en': 'Kannada · English mix',
  'en-kn': 'English · Kannada mix',
  'hi-en': 'Hindi · English mix',
  'en-hi': 'English · Hindi mix',
};

export function languageLabel(code: string | null | undefined): string {
  if (!code) return 'Unknown';
  const key = code.toLowerCase();
  if (LANGUAGES[key]) return LANGUAGES[key];
  const parts = key.split(/[-_]/).map((p) => LANGUAGES[p] ?? p.toUpperCase());
  return parts.join(' · ');
}

export function shortId(id: string | null | undefined, keep = 14): string {
  if (!id) return 'anonymous';
  return id.length <= keep ? id : `${id.slice(0, keep)}…`;
}

export const SEVERITY_LABELS: Record<number, string> = {
  1: 'Cosmetic',
  2: 'Minor',
  3: 'Needs attention',
  4: 'Serious',
  5: 'Danger to life',
};

export function severityLabel(s: number): string {
  return SEVERITY_LABELS[Math.max(1, Math.min(5, Math.round(s)))] ?? '';
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function coordText(lat: number, lng: number): string {
  return `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
}

/** 0..1 confidence → "93%". */
export function fmtConfidence(v: number): string {
  return `${Math.round(clamp(v, 0, 1) * 100)}%`;
}

/** Metres → "12 m" or "1.4 km". */
export function fmtDistance(m: number): string {
  const abs = Math.abs(m);
  if (abs < 1000) return `${Math.round(abs)} m`;
  return `${(abs / 1000).toFixed(abs < 10_000 ? 1 : 0)} km`;
}

/** `{length: 120, width: 80, depth: 15}` → "≈ 120 × 80 cm, 15 cm deep"; null when nothing was estimated. */
export function fmtDimensionsCm(d: EstimatedDimensionsCm | null | undefined): string | null {
  if (!d) return null;
  const cm = (v: number | null | undefined): number | null => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? Math.round(v) : null);
  const length = cm(d.length);
  const width = cm(d.width);
  const depth = cm(d.depth);
  const parts: string[] = [];
  if (length !== null && width !== null) parts.push(`${length} × ${width} cm`);
  else if (length !== null) parts.push(`${length} cm long`);
  else if (width !== null) parts.push(`${width} cm wide`);
  if (depth !== null) parts.push(`${depth} cm deep`);
  return parts.length ? `≈ ${parts.join(', ')}` : null;
}

/** "Ward 150 · Bellandur" when the official ward number is known, else just the name. */
export function wardName(name: string, wardNo?: number | null): string {
  return typeof wardNo === 'number' ? `Ward ${wardNo} · ${name}` : name;
}
