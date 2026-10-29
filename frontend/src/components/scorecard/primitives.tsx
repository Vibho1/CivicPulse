/**
 * Small visual primitives for the ward scorecard: grade badge, bullet chart,
 * lifecycle mix bar. Pure presentational; strings come from the caller.
 */
import type { Grade, WardRow } from '../../api';
import { useI18n } from '../../i18n';
import { pct } from '../../lib/format';

export const GRADE_COLORS: Record<Grade, string> = {
  A: 'var(--verified)',
  B: '#65a30d',
  C: 'var(--open)',
  D: '#ea580c',
  F: 'var(--disputed)',
};

export function GradeBadge({ grade, index, size = 'md', lowData = false }: { grade: Grade; index: number; size?: 'sm' | 'md' | 'lg'; lowData?: boolean }) {
  const { t } = useI18n();
  return (
    <span
      className={`grade grade-${size} grade-${grade}${lowData ? ' grade-low' : ''}`}
      style={{ background: GRADE_COLORS[grade] }}
      role="img"
      aria-label={t('scorecard.grade.aria', { grade, index })}
      title={`${t('scorecard.grade.index', { index })}${lowData ? ` · ${t('scorecard.grade.lowDataTitle')}` : ''}`}
    >
      {grade}
    </span>
  );
}

/**
 * Stephen Few style bullet graph: shaded poor/fair/good bands, a dark bar for the value and
 * a tick for the target. `invert` = lower is better (e.g. SLA breach %).
 */
export function Bullet({ value, target, invert = false, caption }: { value: number | null; target: number; invert?: boolean; caption?: string }) {
  const { t } = useI18n();
  if (value === null || value === undefined) {
    return <span className="muted">—</span>;
  }
  const v = Math.max(0, Math.min(100, value));
  const good = invert ? v <= target : v >= target;
  const mid = invert ? v <= 50 : v >= 50;
  const tone = good ? 'tone-good' : mid ? 'tone-warn' : 'tone-bad';
  return (
    <span className="bullet-wrap" title={t('scorecard.bullet.target', { value: pct(target) })}>
      <span className={`bullet${invert ? ' bullet-inv' : ''}`} aria-hidden="true">
        <span className="bullet-bar" style={{ width: `${v}%` }} />
        <span className="bullet-target" style={{ left: `${target}%` }} />
      </span>
      <span className={`bullet-caption ${tone}`}>{caption ?? pct(v)}</span>
    </span>
  );
}

const MIX_SEGMENTS: { key: keyof Pick<WardRow, 'closure_disputed' | 'open' | 'in_progress' | 'resolved_pending_verification' | 'resolved_verified'>; cls: string }[] = [
  { key: 'closure_disputed', cls: 'mix-disputed' },
  { key: 'open', cls: 'mix-open' },
  { key: 'in_progress', cls: 'mix-in_progress' },
  { key: 'resolved_pending_verification', cls: 'mix-pending' },
  { key: 'resolved_verified', cls: 'mix-verified' },
];

/** 100%-stacked bar of a ward's issues by lifecycle stage, worst on the left. */
export function MixBar({ w, height = 10 }: { w: WardRow; height?: number }) {
  const { t, label } = useI18n();
  const total = MIX_SEGMENTS.reduce((s, seg) => s + (w[seg.key] ?? 0), 0);
  if (!total) return null;
  return (
    <div className="mix-bar" style={{ height }} role="img" aria-label={t('scorecard.mix.label')}>
      {MIX_SEGMENTS.filter((seg) => (w[seg.key] ?? 0) > 0).map((seg) => {
        const n = w[seg.key] ?? 0;
        return <span key={seg.key} className={`mix-seg ${seg.cls}`} style={{ width: `${(100 * n) / total}%` }} title={`${label('status', seg.key)}: ${n}`} />;
      })}
    </div>
  );
}

export function MixLegend() {
  const { label } = useI18n();
  return (
    <div className="mix-legend muted small">
      {MIX_SEGMENTS.map((seg) => (
        <span key={seg.key} className="mix-legend-item">
          <span className={`mix-dot ${seg.cls}`} /> {label('status', seg.key)}
        </span>
      ))}
    </div>
  );
}
