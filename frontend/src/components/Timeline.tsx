import type { TimelineEvent } from '../api';
import { useI18n } from '../i18n';
import { fmtDate, shortId } from '../lib/format';
import { EVENT_LABELS, statusLabel } from '../lib/status';
import { Icon, type IconName } from './Icon';

const ICONS: Record<string, { icon: IconName; tone: string }> = {
  reported: { icon: 'pin', tone: 'info' },
  merged: { icon: 'merge', tone: 'info' },
  corroborated: { icon: 'users', tone: 'info' },
  reopened: { icon: 'rotate', tone: 'bad' },
  status_changed: { icon: 'refresh', tone: 'neutral' },
  resolved: { icon: 'check', tone: 'good' },
  closure_check: { icon: 'eye', tone: 'warn' },
  citizen_verification: { icon: 'camera', tone: 'good' },
  repeat_failure_flagged: { icon: 'flag', tone: 'bad' },
  escalation_drafted: { icon: 'send', tone: 'neutral' },
  verification_requested: { icon: 'bell', tone: 'info' },
  external_ref_recorded: { icon: 'file-text', tone: 'neutral' },
};

function toneFor(e: TimelineEvent): string {
  const base = ICONS[e.type]?.tone ?? 'neutral';
  const verdict = typeof e.payload?.verdict === 'string' ? (e.payload.verdict as string) : null;
  if (verdict) {
    if (verdict === 'VERIFIED') return 'good';
    if (verdict.startsWith('UNVERIFIED')) return 'bad';
    if (verdict === 'NO_PROOF_PROVIDED') return 'warn';
    return 'neutral';
  }
  return base;
}

export function Timeline({ events }: { events: TimelineEvent[] }) {
  const { t, fmt, label } = useI18n();
  if (!events.length) return <p className="muted">{t('timeline.empty')}</p>;
  const sorted = [...events].sort((a, b) => a.created_at.localeCompare(b.created_at));
  return (
    <ol className="timeline">
      {sorted.map((e) => {
        const icon = ICONS[e.type]?.icon ?? 'info';
        const tone = toneFor(e);
        return (
          <li key={e.id} className={`tl-item tone-${tone}`}>
            <span className="tl-dot" aria-hidden="true">
              <Icon name={icon} size={14} />
            </span>
            <div className="tl-body">
              <div className="tl-head">
                <strong>{label('event', e.type, EVENT_LABELS[e.type] ?? e.type.replace(/_/g, ' '))}</strong>
                <time dateTime={e.created_at} title={fmtDate(e.created_at)}>
                  {fmt.timeAgo(e.created_at)}
                </time>
              </div>
              <p>{e.note}</p>
              <div className="tl-meta">
                {t('timeline.by', { actor: shortId(e.actor, 24) })}
                {typeof e.payload?.distance_m === 'number' ? ` · ${t('timeline.away', { distance: fmt.distance(Number(e.payload.distance_m)) })}` : ''}
                {typeof e.payload?.from === 'string' && typeof e.payload?.to === 'string'
                  ? ` · ${t('timeline.transition', {
                      from: label('status', String(e.payload.from), statusLabel(String(e.payload.from))),
                      to: label('status', String(e.payload.to), statusLabel(String(e.payload.to))),
                    })}`
                  : ''}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
