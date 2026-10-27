import type { ClusterStatus, Verdict } from '../api';

export const STATUS_COLORS: Record<ClusterStatus, string> = {
  open: '#f59e0b',
  in_progress: '#3b82f6',
  resolved_pending_verification: '#8b5cf6',
  resolved_verified: '#16a34a',
  closure_disputed: '#dc2626',
};

export const STATUS_LABELS: Record<ClusterStatus, string> = {
  open: 'Open',
  in_progress: 'In progress',
  resolved_pending_verification: 'Resolved - awaiting proof',
  resolved_verified: 'Resolved - verified',
  closure_disputed: 'Closure disputed',
};

export const STATUS_SHORT: Record<ClusterStatus, string> = {
  open: 'Open',
  in_progress: 'In progress',
  resolved_pending_verification: 'Awaiting proof',
  resolved_verified: 'Verified fixed',
  closure_disputed: 'Disputed',
};

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

/** Max points per score component, per docs/API.md. */
export const SCORE_COMPONENT_MAX: Record<string, number> = {
  corroboration: 30,
  severity: 30,
  context: 20,
  hazard: 15,
  sla: 10,
  repeat_failure: 10,
};

export const SCORE_COMPONENT_LABELS: Record<string, string> = {
  corroboration: 'Corroboration',
  severity: 'Severity',
  context: 'Sensitive context',
  hazard: 'Hazards',
  sla: 'SLA overdue',
  repeat_failure: 'Repeat failure',
};

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
};

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
