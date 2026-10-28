import { AGENCY_CODES, type Category, type ClusterStatus, type PhotoFlag, type RepairQuality, type Verdict } from '../api';
import type { IconName } from '../components/Icon';
import { humanize } from './format';

export const STATUS_COLORS: Record<ClusterStatus, string> = {
  open: '#f59e0b',
  in_progress: '#3b82f6',
  resolved_pending_verification: '#8b5cf6',
  resolved_verified: '#16a34a',
  closure_disputed: '#dc2626',
};

/** PRD status names. */
export const STATUS_LABELS: Record<ClusterStatus, string> = {
  open: 'Open',
  in_progress: 'In progress',
  resolved_pending_verification: 'Pending verification',
  resolved_verified: 'Verified resolved',
  closure_disputed: 'Unverified closure',
};

export const STATUS_SHORT: Record<ClusterStatus, string> = {
  open: 'Open',
  in_progress: 'In progress',
  resolved_pending_verification: 'Pending',
  resolved_verified: 'Verified',
  closure_disputed: 'Unverified',
};

/** Label for a status id from an untyped source (e.g. a timeline payload). */
export function statusLabel(s: string): string {
  return (STATUS_LABELS as Record<string, string>)[s] ?? s.replace(/_/g, ' ');
}

export type Tone = 'good' | 'bad' | 'warn' | 'neutral' | 'info';

export function verdictTone(v: Verdict | string | null | undefined): Tone {
  switch (v) {
    case 'VERIFIED':
      return 'good';
    case 'UNVERIFIED_DIFFERENT_LOCATION':
    case 'UNVERIFIED_NOT_FIXED':
    case 'UNVERIFIED_COSMETIC':
      return 'bad';
    case 'NO_PROOF_PROVIDED':
      return 'warn';
    case 'INCONCLUSIVE':
    default:
      return 'neutral';
  }
}

export const VERDICT_LABELS: Record<Verdict, string> = {
  VERIFIED: 'Verified',
  UNVERIFIED_DIFFERENT_LOCATION: 'Unverified — different location',
  UNVERIFIED_NOT_FIXED: 'Unverified — not fixed',
  UNVERIFIED_COSMETIC: 'Unverified — cosmetic patch',
  INCONCLUSIVE: 'Inconclusive',
  NO_PROOF_PROVIDED: 'No proof provided',
};

export const VERDICT_HEADLINES: Record<Verdict, string> = {
  VERIFIED: 'Fix confirmed at the same spot',
  UNVERIFIED_DIFFERENT_LOCATION: 'After-photo is from a different place',
  UNVERIFIED_NOT_FIXED: 'Issue is still there',
  UNVERIFIED_COSMETIC: 'Cosmetic cover-up, not a repair',
  INCONCLUSIVE: 'Could not tell from the photos',
  NO_PROOF_PROVIDED: 'Closed on paper only — no after-photo',
};

export function verdictLabel(v: Verdict | string | null | undefined): string {
  if (!v) return 'No verdict';
  return (VERDICT_LABELS as Record<string, string>)[v] ?? v.replace(/_/g, ' ');
}

export function verdictHeadline(v: Verdict | string | null | undefined): string {
  if (!v) return '';
  return (VERDICT_HEADLINES as Record<string, string>)[v] ?? '';
}

/** Impact score colour: high = urgent (red), mid = amber, low = green. */
export function impactColor(score: number): string {
  if (score >= 70) return '#dc2626';
  if (score >= 45) return '#f59e0b';
  return '#16a34a';
}

/** Max points per score component, per docs/API.md (PRD weights; `meta.score_weights` wins when loaded). */
export const SCORE_COMPONENT_MAX: Record<string, number> = {
  unique_reporters: 35,
  severity: 30,
  context: 20,
  days_elapsed: 15,
};

export const SCORE_COMPONENT_LABELS: Record<string, string> = {
  unique_reporters: 'Unique reporters',
  severity: 'Severity',
  context: 'Road & nearby facilities',
  days_elapsed: 'Days open',
};

/** Max points of a score component: server weights, then PRD defaults; an unknown component is its own max. */
export function scoreComponentMax(component: string, points: number, weights?: Record<string, number> | null): number {
  const max = weights?.[component] ?? SCORE_COMPONENT_MAX[component];
  return typeof max === 'number' && max > 0 ? max : Math.max(0, points);
}

export function scoreComponentLabel(component: string): string {
  return SCORE_COMPONENT_LABELS[component] ?? component;
}

export const EVENT_LABELS: Record<string, string> = {
  reported: 'Reported',
  merged: 'Merged duplicate report',
  corroborated: 'Corroborated',
  reopened: 'Reopened by community',
  status_changed: 'Status changed',
  resolved: 'Marked resolved',
  closure_check: 'AI closure check',
  citizen_verification: 'Citizen verification',
  repeat_failure_flagged: 'Repeat failure flagged',
  escalation_drafted: 'Escalation drafted',
  verification_requested: 'Proof photo requested',
  external_ref_recorded: 'Official ticket linked',
};

export const REPAIR_QUALITY_LABELS: Record<RepairQuality, string> = {
  verified_complete: 'Repair complete',
  temporary_or_partial: 'Temporary / partial repair',
  unrepaired: 'Not repaired',
  mismatched_location: 'Location mismatch',
};

export function repairQualityLabel(q: RepairQuality | string): string {
  return (REPAIR_QUALITY_LABELS as Record<string, string>)[q] ?? humanize(q);
}

/** Chip tone (`chip-<tone>`) for a repair grade. */
export function repairQualityTone(q: RepairQuality | string | null | undefined): 'ok' | 'warn' | 'bad' | 'muted' {
  switch (q) {
    case 'verified_complete':
      return 'ok';
    case 'temporary_or_partial':
      return 'warn';
    case 'unrepaired':
    case 'mismatched_location':
      return 'bad';
    default:
      return 'muted';
  }
}

export interface PhotoFlagInfo {
  label: string;
  /** Chip tone (`chip-<tone>`). */
  tone: 'warn' | 'bad' | 'info' | 'muted';
  icon: IconName;
  title: string;
}

/** How each server-side photo provenance flag is shown. */
export const PHOTO_FLAG_INFO: Record<PhotoFlag, PhotoFlagInfo> = {
  exif_stripped: {
    label: 'No photo metadata (forwarded/stock?)',
    tone: 'warn',
    icon: 'image',
    title: 'The original photo carried no camera metadata, which is typical of forwarded, downloaded or edited images.',
  },
  exif_location_far: {
    label: 'Photo GPS far from pin',
    tone: 'bad',
    icon: 'pin',
    title: 'The location saved in the photo is far from where the issue was pinned.',
  },
  stock_or_screenshot: {
    label: 'Looks like stock/screenshot',
    tone: 'bad',
    icon: 'alert',
    title: 'The image looks like a stock photo or a screenshot rather than a fresh camera shot.',
  },
  faces_or_plates_blurred: {
    label: 'Faces/plates blurred',
    tone: 'info',
    icon: 'eye',
    title: 'Faces or number plates were blurred before the photo was stored.',
  },
};

export function photoFlagInfo(flag: string): PhotoFlagInfo {
  return (PHOTO_FLAG_INFO as Record<string, PhotoFlagInfo>)[flag] ?? { label: humanize(flag), tone: 'muted', icon: 'info', title: '' };
}

/** Chip tone for a 0..1 reporter-credibility score. */
export function credibilityTone(v: number): 'ok' | 'warn' | 'bad' {
  if (v >= 0.7) return 'ok';
  if (v >= 0.4) return 'warn';
  return 'bad';
}

/** PRD agency code ('BBMP_ROADS', 'BTP', …): the server's value, else derived from the agency id. */
export function agencyCode(agency: string | null | undefined, code?: string | null): string | null {
  if (code) return code;
  if (!agency) return null;
  return (AGENCY_CODES as Record<string, string>)[agency] ?? agency;
}

/** Category ids renamed in the PRD-alignment pass (old links may still carry them). */
export const LEGACY_CATEGORY_IDS: Record<string, Category> = {
  streetlight: 'streetlight_outage',
  garbage: 'garbage_dump',
  footpath_damage: 'damaged_footpath',
};

export function normalizeCategory(id: string): string {
  return LEGACY_CATEGORY_IDS[id] ?? id;
}

/** Status-machine helpers (mirror backend/app/services/closure.py). */
export const RESOLVABLE: ClusterStatus[] = ['open', 'in_progress', 'closure_disputed'];
export const VERIFIABLE: ClusterStatus[] = ['resolved_pending_verification', 'closure_disputed'];

export function canSetStatus(current: ClusterStatus, target: 'open' | 'in_progress'): boolean {
  return current !== 'resolved_verified' && current !== target;
}
export function canResolve(current: ClusterStatus): boolean {
  return RESOLVABLE.includes(current);
}
export function canVerify(current: ClusterStatus): boolean {
  return VERIFIABLE.includes(current);
}
export function canCorroborate(current: ClusterStatus): boolean {
  return current !== 'resolved_verified';
}
