import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { Cluster, ClusterStatus, Verdict } from '../api';
import { useApp } from '../context/AppContext';
import { useI18n } from '../i18n';
import {
  STATUS_LABELS,
  STATUS_SHORT,
  impactColor,
  scoreComponentLabel,
  scoreComponentMax,
  verdictLabel,
  verdictTone,
} from '../lib/status';
import { Icon } from './Icon';

// ------------------------------------------------------------------ badges --

/** `short` uses the compact chip wording (Open / Pending / Verified …); `label` overrides both. */
export function StatusBadge({ status, label, short = false, size = 'md' }: { status: ClusterStatus; label?: string; short?: boolean; size?: 'sm' | 'md' }) {
  const { label: vocab } = useI18n();
  return (
    <span className={`badge status-${status} badge-${size}`}>
      <span className="dot" aria-hidden="true" />
      {label ?? (short ? vocab('statusShort', status, STATUS_SHORT[status]) : vocab('status', status, STATUS_LABELS[status]))}
    </span>
  );
}

export function VerdictBadge({ verdict, size = 'md' }: { verdict: Verdict | string | null | undefined; size?: 'sm' | 'md' | 'lg' }) {
  const { t, label: vocab } = useI18n();
  return <span className={`badge tone-${verdictTone(verdict)} badge-${size}`}>{verdict ? vocab('verdict', verdict, verdictLabel(verdict)) : t('verdict.none')}</span>;
}

/** Pass `agency` (the id) to show the translated short/full names; `short`/`label` are the backend fallbacks. */
export function AgencyChip({ agency, short, label, reason }: { agency?: string | null; short: string; label?: string; reason?: string | null }) {
  const { label: vocab } = useI18n();
  const name = agency ? vocab('agency', agency, short) : short;
  const full = agency ? vocab('agencyName', agency, label ?? short) : (label ?? short);
  return (
    <span className="chip chip-agency" title={reason ? `${full}: ${reason}` : full}>
      <Icon name="shield" size={13} />
      {name}
    </span>
  );
}

/** PRD agency code, e.g. BBMP_ROADS for GBA_ROADS or BTP for the traffic police. */
export function AgencyCodeChip({ code }: { code: string | null | undefined }) {
  const { t } = useI18n();
  if (!code) return null;
  return (
    <span className="chip chip-muted chip-code" title={t('routing.codeTitle')}>
      {code}
    </span>
  );
}

export function SlaBadge({ cluster }: { cluster: Pick<Cluster, 'sla_breached' | 'hours_to_sla' | 'status'> }) {
  const { fmt } = useI18n();
  if (cluster.status === 'resolved_verified') return null;
  const breached = cluster.sla_breached || cluster.hours_to_sla < 0;
  return (
    <span className={`chip ${breached ? 'chip-bad' : 'chip-ok'}`}>
      <Icon name="clock" size={13} />
      {fmt.sla(cluster)}
    </span>
  );
}

export function LanguageBadge({ code }: { code: string | null | undefined }) {
  const { t, fmt } = useI18n();
  return (
    <span className="chip chip-lang" title={code ? t('common.languageCode', { code }) : undefined}>
      {fmt.language(code)}
    </span>
  );
}

export function Chip({ children, tone, icon }: { children: ReactNode; tone?: 'ok' | 'bad' | 'warn' | 'info' | 'muted'; icon?: Parameters<typeof Icon>[0]['name'] }) {
  return (
    <span className={`chip${tone ? ` chip-${tone}` : ''}`}>
      {icon ? <Icon name={icon} size={13} /> : null}
      {children}
    </span>
  );
}

// -------------------------------------------------------------- score ring --

export function ScoreRing({ score, size = 64, stroke = 7, showLabel = false }: { score: number; size?: number; stroke?: number; showLabel?: boolean }) {
  const { t } = useI18n();
  const s = Math.max(0, Math.min(100, score || 0));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const color = impactColor(s);
  return (
    <div className="score-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={t('score.aria', { score: Math.round(s) })}>
        <circle cx={size / 2} cy={size / 2} r={r} stroke="#e6e9f2" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={color}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={`${(c * s) / 100} ${c}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        <text x="50%" y={showLabel ? '46%' : '50%'} dominantBaseline="central" textAnchor="middle" fontSize={size * 0.3} fontWeight={700} fill="#0f172a">
          {Math.round(s)}
        </text>
        {showLabel ? (
          <text x="50%" y="68%" dominantBaseline="central" textAnchor="middle" fontSize={size * 0.11} fill="#64748b" letterSpacing="0.08em">
            {t('score.ring')}
          </text>
        ) : null}
      </svg>
    </div>
  );
}

export function ScoreBreakdownBars({ cluster }: { cluster: Cluster }) {
  const { meta } = useApp();
  const { t, has, label: vocab } = useI18n();
  const comps = cluster.score_breakdown?.components ?? [];
  if (!comps.length) return <p className="muted">{t('score.noBreakdown')}</p>;
  return (
    <ul className="bars" aria-label={t('score.breakdown')}>
      {comps.map((c) => {
        const max = scoreComponentMax(c.component, c.points, meta?.score_weights);
        const w = max > 0 ? Math.max(0, Math.min(100, (c.points / max) * 100)) : 0;
        return (
          <li key={c.component} className="bar-row">
            <div className="bar-head">
              <span className="bar-label" title={has(`scoreComponentHint.${c.component}`) ? t(`scoreComponentHint.${c.component}`) : undefined}>
                {vocab('scoreComponent', c.component, scoreComponentLabel(c.component))}
              </span>
              <span className="bar-value">
                {c.points.toFixed(1)}
                <span className="muted"> / {Number.isInteger(max) ? max : max.toFixed(1)}</span>
              </span>
            </div>
            <div className="bar-track" role="presentation">
              <div className="bar-fill" style={{ width: `${w}%` }} />
            </div>
            <div className="bar-reason">{c.reason}</div>
          </li>
        );
      })}
    </ul>
  );
}

// ---------------------------------------------------------------- severity --

export function SeverityMeter({ severity, compact = false }: { severity: number; compact?: boolean }) {
  const { t, fmt } = useI18n();
  const s = Math.max(1, Math.min(5, Math.round(severity || 1)));
  return (
    <div className={`meter${compact ? ' meter-compact' : ''}`} role="img" aria-label={t('meter.aria', { level: s, label: fmt.severity(s) })}>
      <div className="meter-segments">
        {[1, 2, 3, 4, 5].map((i) => (
          <span key={i} className={`meter-seg${i <= s ? ` on sev-${s}` : ''}`} />
        ))}
      </div>
      {!compact ? (
        <span className="meter-text">{t('meter.text', { level: s, label: fmt.severity(s) })}</span>
      ) : (
        <span className="meter-text">{s}/5</span>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ SLA bar --

export function SlaBar({ cluster }: { cluster: Cluster }) {
  const { t, tx, label: vocab, fmt } = useI18n();
  const breached = cluster.sla_breached || cluster.hours_to_sla < 0;
  const closed = cluster.status === 'resolved_verified';
  const ratio = cluster.sla_hours > 0 ? Math.min(1, cluster.hours_open / cluster.sla_hours) : 1;
  return (
    <div className={`sla ${breached && !closed ? 'sla-breached' : 'sla-ok'}`}>
      <div className="sla-head">
        <span>{tx('sla.openFor', { time: <strong>{fmt.duration(cluster.hours_open)}</strong> })}</span>
        <span className="muted">{t('sla.target', { hours: cluster.sla_hours })}</span>
      </div>
      <div className="sla-track" role="progressbar" aria-valuemin={0} aria-valuemax={cluster.sla_hours} aria-valuenow={Math.min(cluster.hours_open, cluster.sla_hours)}>
        <div className="sla-fill" style={{ width: `${ratio * 100}%` }} />
      </div>
      <div className="sla-foot">
        {closed ? (
          <span className="chip chip-ok">
            <Icon name="check" size={13} /> {t('sla.closedVerified')}
          </span>
        ) : breached ? (
          <span className="chip chip-bad">
            <Icon name="alert" size={13} /> {t('sla.breachedShort', { time: fmt.duration(-cluster.hours_to_sla) })}
          </span>
        ) : (
          <span className="chip chip-ok">
            <Icon name="clock" size={13} /> {t('sla.dueShort', { time: fmt.duration(cluster.hours_to_sla) })}
          </span>
        )}
        <span className="muted small">{t('sla.charter', { category: vocab('category', cluster.category, cluster.category_label).toLowerCase() })}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- feedback --

export function Spinner({ size = 18, label }: { size?: number; label?: string }) {
  const { t } = useI18n();
  return (
    <span className="spinner-wrap" role="status" aria-live="polite">
      <span className="spinner" style={{ width: size, height: size }} aria-hidden="true" />
      {label ? <span>{label}</span> : <span className="sr-only">{t('common.loading')}</span>}
    </span>
  );
}

export function Skeleton({ h = 16, w = '100%', r = 8, className = '' }: { h?: number | string; w?: number | string; r?: number; className?: string }) {
  return <span className={`skeleton ${className}`} style={{ height: h, width: w, borderRadius: r }} aria-hidden="true" />;
}

export function EmptyState({ title, body, children, icon = 'search' }: { title: string; body?: ReactNode; children?: ReactNode; icon?: Parameters<typeof Icon>[0]['name'] }) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon name={icon} size={28} />
      </div>
      <h3>{title}</h3>
      {body ? <p>{body}</p> : null}
      {children ? <div className="empty-actions">{children}</div> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { t } = useI18n();
  return (
    <div className="empty empty-error" role="alert">
      <div className="empty-icon">
        <Icon name="alert" size={28} />
      </div>
      <h3>{t('error.title')}</h3>
      <p>{message}</p>
      <div className="empty-actions">
        {onRetry ? (
          <button type="button" className="btn btn-primary" onClick={onRetry}>
            <Icon name="refresh" size={16} /> {t('common.retry')}
          </button>
        ) : null}
        <Link to="/" className="btn btn-ghost">
          {t('common.backToMap')}
        </Link>
      </div>
    </div>
  );
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="section-title">
      <h2>{children}</h2>
      {aside ? <div className="section-aside">{aside}</div> : null}
    </div>
  );
}
