/**
 * Locale-aware versions of the lib/format.ts helpers that produce user-facing text (relative
 * times, durations, SLA chips, counts, sizes, ward names, spoken-language names). Thresholds match
 * lib/format.ts, so English output is unchanged. Exposed as `useI18n().fmt`.
 */
import { fmtDate } from '../lib/format';
import type { Key, Vars } from './index';

type Translate = (key: Key, vars?: Vars) => string;
type TranslatePlural = (key: string, count: number, vars?: Vars) => string;

const HOUR = 3_600_000;

/** The cluster fields the SLA chip needs (structural, so callers can pass any cluster shape). */
export interface SlaFields {
  status: string;
  sla_breached: boolean;
  hours_to_sla: number;
}

/** Parser size estimate in centimetres; any part may be unknown. */
export interface DimensionsCm {
  length?: number | null;
  width?: number | null;
  depth?: number | null;
}

export interface Formatters {
  /** "just now", "12 min ago", "3 h ago", "6 d ago", "2 mo ago" (or "in 5 h" for future times). */
  timeAgo: (iso: string | null | undefined, now?: Date) => string;
  /** Hours → "45 min", "5.5 h" or "3.1 d"; '—' when missing. */
  duration: (hours: number | null | undefined) => string;
  /** "Closed" / "SLA breached by 5.5 h" / "SLA due in 3.1 d". */
  sla: (c: SlaFields) => string;
  /** PRD date format (YYYY-MM-DD, India time), the same in both languages: lib/format.ts `fmtDate`. */
  date: (iso: string | null | undefined, opts?: { time?: boolean }) => string;
  /** Metres → "12 m" or "1.4 km". */
  distance: (m: number) => string;
  /** Centimetres → "15 cm". */
  cm: (value: number) => string;
  /** "≈ 120 × 80 cm, 15 cm deep"; null when nothing was estimated. */
  dimensions: (d: DimensionsCm | null | undefined) => string | null;
  /** `count('report', 3)` → "3 reports" (reads the `count.report.one/other` keys). */
  count: (noun: string, n: number) => string;
  /** Spoken-language code ("kn", "kn-en", …) → display name. */
  language: (code: string | null | undefined) => string;
  /** 1-5 severity → "Needs attention" etc. */
  severity: (s: number) => string;
  /** Translated ward name, prefixed with the official number when known: "Ward 150 · Bellandur". */
  ward: (name: string, wardNo?: number | null) => string;
}

function parseIso(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function createFormatters(t: Translate, tn: TranslatePlural, has: (key: Key) => boolean): Formatters {
  function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
    const d = parseIso(iso);
    if (!d) return '';
    const diff = now.getTime() - d.getTime();
    const abs = Math.abs(diff);
    const min = Math.round(abs / 60_000);
    if (min < 1) return t('time.justNow');
    const dir = diff < 0 ? 'in' : 'ago';
    if (min < 60) return tn(`time.${dir}.min`, min);
    if (abs < 48 * HOUR) return tn(`time.${dir}.h`, Math.round(abs / HOUR));
    if (abs < 60 * 24 * HOUR) return tn(`time.${dir}.d`, Math.round(abs / (24 * HOUR)));
    return tn(`time.${dir}.mo`, Math.round(abs / (30 * 24 * HOUR)));
  }

  function duration(hours: number | null | undefined): string {
    if (hours === null || hours === undefined || Number.isNaN(hours)) return '—';
    const h = Math.abs(hours);
    if (h < 1) return t('unit.min', { n: Math.round(h * 60) });
    if (h < 48) return t('unit.h', { n: Math.round(h * 10) / 10 });
    return t('unit.d', { n: Math.round((h / 24) * 10) / 10 });
  }

  function sla(c: SlaFields): string {
    if (c.status === 'resolved_verified') return t('sla.closed');
    if (c.sla_breached || c.hours_to_sla < 0) return t('sla.breachedBy', { time: duration(-c.hours_to_sla) });
    return t('sla.dueIn', { time: duration(c.hours_to_sla) });
  }

  function distance(m: number): string {
    const abs = Math.abs(m);
    if (abs < 1000) return t('unit.m', { n: Math.round(abs) });
    return t('unit.km', { n: (abs / 1000).toFixed(abs < 10_000 ? 1 : 0) });
  }

  function dimensions(d: DimensionsCm | null | undefined): string | null {
    if (!d) return null;
    const cm = (v: number | null | undefined): number | null => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? Math.round(v) : null);
    const length = cm(d.length);
    const width = cm(d.width);
    const depth = cm(d.depth);
    const parts: string[] = [];
    if (length !== null && width !== null) parts.push(t('dims.lw', { length, width }));
    else if (length !== null) parts.push(t('dims.length', { value: length }));
    else if (width !== null) parts.push(t('dims.width', { value: width }));
    if (depth !== null) parts.push(t('dims.depth', { value: depth }));
    return parts.length ? t('dims.approx', { value: parts.join(', ') }) : null;
  }

  function language(code: string | null | undefined): string {
    if (!code) return t('language.unknown');
    const key = code.toLowerCase();
    if (has(`language.${key}`)) return t(`language.${key}`);
    return key
      .split(/[-_]/)
      .map((p) => (has(`language.${p}`) ? t(`language.${p}`) : p.toUpperCase()))
      .join(' · ');
  }

  function ward(name: string, wardNo?: number | null): string {
    const local = has(`ward.${name}`) ? t(`ward.${name}`) : name;
    return typeof wardNo === 'number' ? t('common.wardWithNumber', { number: wardNo, name: local }) : local;
  }

  return {
    timeAgo,
    duration,
    sla,
    date: fmtDate,
    distance,
    cm: (value) => t('unit.cm', { n: Math.round(value) }),
    dimensions,
    count: (noun, n) => tn(`count.${noun}`, n),
    language,
    severity: (s) => t(`severity.${Math.max(1, Math.min(5, Math.round(s || 1)))}`),
    ward,
  };
}
