import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { Cluster, ClusterStatus, Verdict } from '../api';
import { fmtHours, languageLabel, severityLabel, slaText } from '../lib/format';
import {
  SCORE_COMPONENT_LABELS,
  SCORE_COMPONENT_MAX,
  STATUS_LABELS,
  impactColor,
  verdictLabel,
  verdictTone,
} from '../lib/status';
import { Icon } from './Icon';

// ------------------------------------------------------------------ badges --

export function StatusBadge({ status, label, size = 'md' }: { status: ClusterStatus; label?: string; size?: 'sm' | 'md' }) {
  return (
    <span className={`badge status-${status} badge-${size}`}>
      <span className="dot" aria-hidden="true" />
      {label ?? STATUS_LABELS[status]}
    </span>
  );
}

export function VerdictBadge({ verdict, size = 'md' }: { verdict: Verdict | string | null | undefined; size?: 'sm' | 'md' | 'lg' }) {
  return <span className={`badge tone-${verdictTone(verdict)} badge-${size}`}>{verdictLabel(verdict)}</span>;
}

export function AgencyChip({ short, label, reason }: { short: string; label?: string; reason?: string | null }) {
  return (
    <span className="chip chip-agency" title={reason ? `${label ?? short}: ${reason}` : label ?? short}>
      <Icon name="shield" size={13} />
      {short}
    </span>
  );
}

export function SlaBadge({ cluster }: { cluster: Pick<Cluster, 'sla_breached' | 'hours_to_sla' | 'status'> }) {
  if (cluster.status === 'resolved_verified') return null;
  const breached = cluster.sla_breached || cluster.hours_to_sla < 0;
  return (
    <span className={`chip ${breached ? 'chip-bad' : 'chip-ok'}`}>
      <Icon name="clock" size={13} />
      {slaText(cluster)}
    </span>
  );
}

export function LanguageBadge({ code }: { code: string | null | undefined }) {
  return (
    <span className="chip chip-lang" title={code ? `Language code: ${code}` : undefined}>
      {languageLabel(code)}
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
  const s = Math.max(0, Math.min(100, score || 0));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const color = impactColor(s);
  return (
    <div className="score-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`Impact score ${Math.round(s)} out of 100`}>
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
            IMPACT
          </text>
        ) : null}
      </svg>
    </div>
  );
}

export function ScoreBreakdownBars({ cluster }: { cluster: Cluster }) {
  const comps = cluster.score_breakdown?.components ?? [];
  if (!comps.length) return <p className="muted">No breakdown available.</p>;
  return (
    <ul className="bars" aria-label="Impact score breakdown">
      {comps.map((c) => {
        const max = SCORE_COMPONENT_MAX[c.component] ?? 30;
        const w = Math.max(0, Math.min(100, (c.points / max) * 100));
        return (
          <li key={c.component} className="bar-row">
            <div className="bar-head">
              <span className="bar-label">{SCORE_COMPONENT_LABELS[c.component] ?? c.component}</span>
              <span className="bar-value">
                {c.points.toFixed(1)}
                <span className="muted"> / {max}</span>
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
  const s = Math.max(1, Math.min(5, Math.round(severity || 1)));
  return (
    <div className={`meter${compact ? ' meter-compact' : ''}`} role="img" aria-label={`Severity ${s} of 5: ${severityLabel(s)}`}>
      <div className="meter-segments">
        {[1, 2, 3, 4, 5].map((i) => (
          <span key={i} className={`meter-seg${i <= s ? ` on sev-${s}` : ''}`} />
        ))}
      </div>
      {!compact ? (
        <span className="meter-text">
          Severity {s}/5 · {severityLabel(s)}
        </span>
      ) : (
        <span className="meter-text">{s}/5</span>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ SLA bar --

export function SlaBar({ cluster }: { cluster: Cluster }) {
  const breached = cluster.sla_breached || cluster.hours_to_sla < 0;
  const closed = cluster.status === 'resolved_verified';
  const ratio = cluster.sla_hours > 0 ? Math.min(1, cluster.hours_open / cluster.sla_hours) : 1;
  return (
    <div className={`sla ${breached && !closed ? 'sla-breached' : 'sla-ok'}`}>
      <div className="sla-head">
        <span>
          Open for <strong>{fmtHours(cluster.hours_open)}</strong>
        </span>
        <span className="muted">SLA {cluster.sla_hours} h</span>
      </div>
      <div className="sla-track" role="progressbar" aria-valuemin={0} aria-valuemax={cluster.sla_hours} aria-valuenow={Math.min(cluster.hours_open, cluster.sla_hours)}>
        <div className="sla-fill" style={{ width: `${ratio * 100}%` }} />
      </div>
      <div className="sla-foot">
        {closed ? (
          <span className="chip chip-ok">
            <Icon name="check" size={13} /> Closed and verified
          </span>
        ) : breached ? (
          <span className="chip chip-bad">
            <Icon name="alert" size={13} /> Breached by {fmtHours(-cluster.hours_to_sla)}
          </span>
        ) : (
          <span className="chip chip-ok">
            <Icon name="clock" size={13} /> Due in {fmtHours(cluster.hours_to_sla)}
          </span>
        )}
        <span className="muted small">Citizen-charter style target for {cluster.category_label.toLowerCase()}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- feedback --

export function Spinner({ size = 18, label }: { size?: number; label?: string }) {
  return (
    <span className="spinner-wrap" role="status" aria-live="polite">
      <span className="spinner" style={{ width: size, height: size }} aria-hidden="true" />
      {label ? <span>{label}</span> : <span className="sr-only">Loading</span>}
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
  return (
    <div className="empty empty-error" role="alert">
      <div className="empty-icon">
        <Icon name="alert" size={28} />
      </div>
      <h3>Something went wrong</h3>
      <p>{message}</p>
      <div className="empty-actions">
        {onRetry ? (
          <button type="button" className="btn btn-primary" onClick={onRetry}>
            <Icon name="refresh" size={16} /> Try again
          </button>
        ) : null}
        <Link to="/" className="btn btn-ghost">
          Back to map
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
