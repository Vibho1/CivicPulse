/**
 * UI localisation: Kannada + English (PRD NFR "UI strings in Kannada and English").
 *
 * - `I18nProvider` holds the active language, persists it in localStorage (`cp.lang`), and keeps
 *   `<html lang>` in sync so the `:lang(kn)` typography in i18n.css applies.
 * - `useI18n()` returns `t(key, vars)` with `{name}` interpolation and kn → en → key fallback,
 *   `tn(key, count)` for `.one` / `.other` plural keys, `tx(key, nodes)` for sentences that embed
 *   links or <strong>, `label(family, id, fallback)` for vocabulary keyed by backend IDs, and
 *   `fmt` (locale-aware time / duration / SLA / count formatters).
 *
 * Only UI chrome is translated. Backend free text (AI explanations, transcripts, score reasons,
 * event notes, escalation drafts) is shown as received.
 */
import {
  Fragment,
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import en, { type MessageKey } from './en';
import { createFormatters, type Formatters } from './format';
import kn from './kn';
import './i18n.css';

export type Lang = 'en' | 'kn';
/** Toggle order: EN | ಕನ್ನಡ. */
export const LANGS: readonly Lang[] = ['en', 'kn'];
/** localStorage key for the user's choice. */
export const LANG_STORAGE_KEY = 'cp.lang';

/** Values for `{name}` placeholders. */
export type Vars = Record<string, string | number>;
/** Placeholder values that may be React nodes (links, <strong>, <code>). */
export type RichVars = Record<string, ReactNode>;
/** Known keys autocomplete; computed keys (`category.${id}`) are accepted too. */
export type Key = MessageKey | (string & {});

/** Vocabulary families keyed by backend IDs: `label('category', 'pothole', c.category_label)`. */
export type LabelFamily =
  | 'category'
  | 'status'
  | 'statusShort'
  | 'statusHint'
  | 'agency'
  | 'agencyName'
  | 'agencyScope'
  | 'agencyContact'
  | 'hazard'
  | 'verdict'
  | 'verdictHeadline'
  | 'repairQuality'
  | 'fixQuality'
  | 'severity'
  | 'severityLevel'
  | 'scoreComponent'
  | 'scoreComponentHint'
  | 'event'
  | 'photoFlag'
  | 'photoFlagHint'
  | 'language'
  | 'utility'
  | 'ward'
  | 'zone'
  | 'apiError';

export interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  /** BCP 47 locale for Intl APIs: 'en-IN' or 'kn-IN'. */
  locale: string;
  /** Translate `key`, filling `{name}` placeholders. Falls back kn → en → the key itself. */
  t: (key: Key, vars?: Vars) => string;
  /** Plural-aware: reads `<key>.one` / `<key>.other` (CLDR rules for the language) and adds `{count}`. */
  tn: (key: string, count: number, vars?: Vars) => string;
  /** Like `t`, but placeholders may be React nodes; returns renderable nodes. */
  tx: (key: Key, vars: RichVars) => ReactNode;
  /** Whether `key` exists in the active language or in English. */
  has: (key: Key) => boolean;
  /** Label for a backend ID, e.g. `label('status', c.status, c.status_label)`; falls back to `fallback`, then the humanised ID. */
  label: (family: LabelFamily, id: string | null | undefined, fallback?: string | null) => string;
  fmt: Formatters;
}

type Dict = Readonly<Partial<Record<string, string>>>;

const DICTS: Record<Lang, Dict> = { en, kn };
const LOCALES: Record<Lang, string> = { en: 'en-IN', kn: 'kn-IN' };
const VAR_RE = /\{(\w+)\}/g;

export function isLang(v: unknown): v is Lang {
  return v === 'en' || v === 'kn';
}

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // private mode / quota: the choice still lasts for this session
  }
}

/** `?lang=kn` / `?lang=en` in the URL, e.g. a shared demo link. */
function urlLang(): Lang | null {
  if (typeof window === 'undefined') return null;
  try {
    const q = new URLSearchParams(window.location.search).get('lang');
    return isLang(q) ? q : null;
  } catch {
    return null;
  }
}

/** URL `?lang=`, else the stored choice, else the browser language (kn* → Kannada), else English. */
export function detectLang(): Lang {
  const fromUrl = urlLang();
  if (fromUrl) return fromUrl;
  if (typeof window === 'undefined') return 'en';
  const stored = safeGet(LANG_STORAGE_KEY);
  if (isLang(stored)) return stored;
  const nav = typeof navigator === 'undefined' ? '' : navigator.language || '';
  return nav.toLowerCase().startsWith('kn') ? 'kn' : 'en';
}

let currentLang: Lang | null = null;

/** Active language for code outside React (prefer `useI18n()` in components). */
export function getLang(): Lang {
  if (!currentLang) currentLang = detectLang();
  return currentLang;
}

function chain(lang: Lang): Lang[] {
  return lang === 'en' ? ['en'] : [lang, 'en'];
}

function lookup(lang: Lang, key: string): string | undefined {
  for (const l of chain(lang)) {
    const hit = DICTS[l][key];
    if (hit !== undefined) return hit;
  }
  return undefined;
}

const pluralRules = new Map<Lang, Intl.PluralRules>();

function pluralCategory(lang: Lang, n: number): Intl.LDMLPluralRule {
  let rules = pluralRules.get(lang);
  if (!rules) {
    rules = new Intl.PluralRules(LOCALES[lang]);
    pluralRules.set(lang, rules);
  }
  return rules.select(n);
}

function lookupPlural(lang: Lang, key: string, count: number): string | undefined {
  for (const l of chain(lang)) {
    const dict = DICTS[l];
    const hit = dict[`${key}.${pluralCategory(l, count)}`] ?? dict[`${key}.other`] ?? dict[key];
    if (hit !== undefined) return hit;
  }
  return undefined;
}

const warned = new Set<string>();

function warnMissing(key: string): void {
  if (!import.meta.env.DEV || warned.has(key)) return;
  warned.add(key);
  console.warn(`[i18n] missing key: ${key}`);
}

function interpolate(template: string, vars?: Vars): string {
  if (!vars) return template;
  return template.replace(VAR_RE, (whole, name: string) => (Object.hasOwn(vars, name) ? String(vars[name]) : whole));
}

function interpolateRich(template: string, vars: RichVars): ReactNode {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of template.matchAll(VAR_RE)) {
    const [whole, name] = m;
    const at = m.index ?? 0;
    if (at > last) out.push(template.slice(last, at));
    out.push(Object.hasOwn(vars, name) ? createElement(Fragment, { key: out.length }, vars[name]) : whole);
    last = at + whole.length;
  }
  if (last < template.length) out.push(template.slice(last));
  return out;
}

/** "two_wheeler_skid_risk" → "Two wheeler skid risk" (last-resort label for unknown IDs). */
function humanizeId(id: string): string {
  const s = id.replace(/[_-]+/g, ' ').trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Translate outside React (prefer `useI18n().t` in components). */
export function translate(lang: Lang, key: Key, vars?: Vars): string {
  const hit = lookup(lang, key);
  if (hit === undefined) {
    warnMissing(key);
    return key;
  }
  return interpolate(hit, vars);
}

/** Plural-aware `translate`: `<key>.one` / `<key>.other`, with `{count}` filled in. */
export function translatePlural(lang: Lang, key: string, count: number, vars?: Vars): string {
  const hit = lookupPlural(lang, key, count);
  if (hit === undefined) {
    warnMissing(`${key}.other`);
    return key;
  }
  return interpolate(hit, { count, ...vars });
}

// Dev-only completeness report: untranslated keys and placeholder mismatches between en and kn.
if (import.meta.env.DEV) {
  const placeholders = (s: string) => [...s.matchAll(VAR_RE)].map((m) => m[1]).sort().join(',');
  const enDict: Dict = en;
  const knDict: Dict = kn;
  const missing = Object.keys(enDict).filter((k) => knDict[k] === undefined);
  if (missing.length) console.info(`[i18n] ${missing.length} key(s) have no Kannada string yet (English is shown):`, missing);
  for (const [k, v] of Object.entries(knDict)) {
    const base = enDict[k];
    if (v !== undefined && base !== undefined && placeholders(v) !== placeholders(base)) {
      console.warn(`[i18n] placeholder mismatch for ${k}: en {${placeholders(base)}} vs kn {${placeholders(v)}}`);
    }
  }
}

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ children, initialLang }: { children: ReactNode; initialLang?: Lang }) {
  const [lang, setLangState] = useState<Lang>(() => initialLang ?? detectLang());

  const setLang = useCallback((next: Lang) => {
    if (!isLang(next)) return;
    setLangState(next);
    safeSet(LANG_STORAGE_KEY, next);
  }, []);

  // A `?lang=` link is an explicit choice: remember it.
  useEffect(() => {
    const fromUrl = urlLang();
    if (fromUrl) safeSet(LANG_STORAGE_KEY, fromUrl);
  }, []);

  // Before paint, so `:lang(kn)` typography never flashes the English font stack.
  useLayoutEffect(() => {
    currentLang = lang;
    document.documentElement.lang = lang;
    document.title = translate(lang, 'app.documentTitle');
  }, [lang]);

  // Follow a switch made in another tab.
  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key === LANG_STORAGE_KEY && isLang(e.newValue)) setLangState(e.newValue);
    }
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const value = useMemo<I18n>(() => {
    const t = (key: Key, vars?: Vars) => translate(lang, key, vars);
    const tn = (key: string, count: number, vars?: Vars) => translatePlural(lang, key, count, vars);
    const has = (key: Key) => lookup(lang, key) !== undefined;
    const tx = (key: Key, vars: RichVars): ReactNode => {
      const hit = lookup(lang, key);
      if (hit === undefined) {
        warnMissing(key);
        return key;
      }
      return interpolateRich(hit, vars);
    };
    const label = (family: LabelFamily, id: string | null | undefined, fallback?: string | null) => {
      if (!id) return fallback ?? '';
      const hit = lookup(lang, `${family}.${id}`);
      if (hit !== undefined) return hit;
      return fallback || humanizeId(id);
    };
    return { lang, setLang, locale: LOCALES[lang], t, tn, tx, has, label, fmt: createFormatters(t, tn, has) };
  }, [lang, setLang]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used inside <I18nProvider>');
  return ctx;
}
