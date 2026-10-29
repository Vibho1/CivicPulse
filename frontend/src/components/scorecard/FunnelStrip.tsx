/**
 * City-level closure funnel: reports → issues → closed → AI-checked → citizen-verified,
 * with the drop-off spelled out in one sentence. Replaces the row of nine stat boxes.
 */
import type { CityStats } from '../../api';
import { Icon } from '../Icon';
import { useI18n } from '../../i18n';
import { pct } from '../../lib/format';

interface Stage {
  key: string;
  value: number;
  label: string;
  note?: string;
  cls: string;
}

export function FunnelStrip({ city }: { city: CityStats }) {
  const { t, tn } = useI18n();
  const f = city.funnel;
  const max = Math.max(1, f.reports);

  const stages: Stage[] = [
    { key: 'reports', value: f.reports, label: t('scorecard.funnel.reports'), cls: 'funnel-ink' },
    {
      key: 'issues',
      value: f.issues,
      label: t('scorecard.funnel.issues'),
      note: f.duplicates_merged_pct ? t('scorecard.funnel.issuesNote', { value: pct(f.duplicates_merged_pct) }) : undefined,
      cls: 'funnel-ink2',
    },
    { key: 'closed', value: f.closed, label: t('scorecard.funnel.closed'), cls: 'funnel-pending' },
    {
      key: 'ai',
      value: f.ai_checked,
      label: t('scorecard.funnel.aiChecked'),
      note: f.no_proof ? tn('scorecard.funnel.aiCheckedNote', f.no_proof) : undefined,
      cls: 'funnel-pending2',
    },
    { key: 'verified', value: f.citizen_verified, label: t('scorecard.funnel.verified'), cls: 'funnel-verified' },
  ];

  let headline: string;
  let headlineTone: string;
  if (f.closed === 0) {
    headline = t('scorecard.funnel.headlineNone');
    headlineTone = 'tone-neutral';
  } else if ((f.unverified_closure_rate ?? 0) === 0) {
    headline = t('scorecard.funnel.headlineGood');
    headlineTone = 'tone-good';
  } else {
    headline = t('scorecard.funnel.headline', { rate: pct(f.unverified_closure_rate), disputed: f.disputed, awaiting: f.awaiting_proof });
    headlineTone = 'tone-bad';
  }

  return (
    <section className="card funnel" aria-label={t('scorecard.funnel.title')}>
      <div className="funnel-head">
        <h2 className="block-title">{t('scorecard.funnel.title')}</h2>
        <div className="chips">
          <span className={`chip ${city.sla_breached_open ? 'chip-bad' : 'chip-muted'}`}>
            <Icon name="clock" size={13} /> {t('scorecard.funnel.slaChip', { count: city.sla_breached_open })}
          </span>
          <span className={`chip ${city.repeat_failures ? 'chip-warn' : 'chip-muted'}`}>
            <Icon name="refresh" size={13} /> {t('scorecard.funnel.repeatChip', { count: city.repeat_failures })}
          </span>
        </div>
      </div>
      <ol className="funnel-stages">
        {stages.map((s, i) => {
          const ratio = s.value / max;
          const height = 36 + Math.round(72 * ratio);
          return (
            <li key={s.key} className="funnel-stage">
              <div className="funnel-value">{s.value}</div>
              <div className={`funnel-bar ${s.cls}`} style={{ height }} aria-hidden="true" />
              <div className="funnel-label">{s.label}</div>
              {s.note ? <div className="funnel-note">{s.note}</div> : null}
              {i < stages.length - 1 ? <span className="funnel-arrow" aria-hidden="true">›</span> : null}
            </li>
          );
        })}
      </ol>
      <p className={`funnel-headline ${headlineTone}`}>{headline}</p>
    </section>
  );
}
