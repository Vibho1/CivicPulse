/**
 * One ward as a report card: grade, accountability index, lifecycle mix, three KPIs and the
 * single issue the ward should be most embarrassed about. Used for every screen width.
 */
import { Link, useNavigate } from 'react-router-dom';
import type { TopProblem, WardRow } from '../../api';
import { Icon } from '../Icon';
import { useI18n } from '../../i18n';
import { pct } from '../../lib/format';
import { GradeBadge, MixBar } from './primitives';

interface Props {
  w: WardRow;
  agencyName: (id: string) => string;
  canEscalate: boolean;
  onEscalate: (w: WardRow) => void;
}

function useProblemSentence() {
  const { t, label, fmt } = useI18n();
  return (p: TopProblem | null): string => {
    if (!p) return t('scorecard.problem.none');
    const vars = {
      title: p.title,
      reports: fmt.count('report', p.report_count),
      agency: label('agency', p.agency),
      time: fmt.duration(p.hours_overdue),
      verdict: p.verification_verdict ? label('verdict', p.verification_verdict) : '',
    };
    return t(`scorecard.problem.${p.kind}`, vars);
  };
}

export function WardReportCard({ w, agencyName, canEscalate, onEscalate }: Props) {
  const { t, label, fmt } = useI18n();
  const navigate = useNavigate();
  const sentence = useProblemSentence()(w.top_problem);
  const mapHref = `/?ward=${encodeURIComponent(w.ward)}`;
  const slaTone = (w.sla_breach_rate ?? 0) >= 50 ? 'tone-bad' : (w.sla_breach_rate ?? 0) > 0 ? 'tone-warn' : 'tone-good';
  const repeatTone = (w.repeat_failure_rate ?? 0) > 0 ? 'tone-warn' : '';
  const problemTone = w.top_problem ? (w.top_problem.kind === 'disputed' || w.top_problem.kind === 'repeat_failure' ? 'rcard-problem-bad' : w.top_problem.kind === 'overdue' ? 'rcard-problem-warn' : '') : 'rcard-problem-good';

  return (
    <li className={`card rcard rcard-${w.grade}`}>
      <div className="rcard-head">
        <GradeBadge grade={w.grade} index={w.accountability_index} size="lg" lowData={w.low_data} />
        <div className="rcard-title">
          <div className="rcard-name">
            <span className="rcard-rank" title={t('scorecard.col.rank')}>#{w.rank}</span> {fmt.ward(w.ward, w.number)}
          </div>
          <div className="muted small">
            {t('common.zone', { zone: label('zone', w.zone, w.zone) })} · {t('scorecard.grade.index', { index: w.accountability_index })}
            {w.low_data ? (
              <span className="chip chip-muted chip-sm" title={t('scorecard.grade.lowDataTitle')}>
                {t('scorecard.grade.lowData')}
              </span>
            ) : null}
          </div>
        </div>
      </div>

      <div className="rcard-mix">
        <div className="bar-head">
          <span className="bar-label">{fmt.count('issue', w.total)}</span>
          <span className="bar-value">
            {w.closures ? (
              <span className={(w.verified_closure_rate ?? 0) >= 75 ? 'tone-good' : (w.verified_closure_rate ?? 0) >= 50 ? 'tone-warn' : 'tone-bad'}>
                {t('scorecard.card.verified', { value: pct(w.verified_closure_rate) })}
              </span>
            ) : (
              <span className="muted">{t('scorecard.card.noClosures')}</span>
            )}
          </span>
        </div>
        <MixBar w={w} height={12} />
      </div>

      <div className="rcard-kpis">
        <div>
          <span className={`rcard-kpi-value ${slaTone}`}>{pct(w.sla_breach_rate)}</span>
          <span className="rcard-kpi-label">{t('scorecard.kpi.slaBreach')}</span>
        </div>
        <div>
          <span className="rcard-kpi-value">{w.avg_hours_to_close === null ? '—' : fmt.duration(w.avg_hours_to_close)}</span>
          <span className="rcard-kpi-label">{t('scorecard.kpi.avgClose')}</span>
        </div>
        <div>
          <span className={`rcard-kpi-value ${repeatTone}`}>{pct(w.repeat_failure_rate)}</span>
          <span className="rcard-kpi-label">{t('scorecard.kpi.repeat')}</span>
        </div>
      </div>

      <div className={`rcard-problem ${problemTone}`}>
        <span className="rcard-problem-title">{t('scorecard.problem.title')}</span>
        <span className="rcard-problem-text">{sentence}</span>
        {w.top_problem ? (
          <Link className="rcard-problem-link" to={`/clusters/${encodeURIComponent(w.top_problem.cluster_id)}`}>
            {t('scorecard.openIssue')} <Icon name="external" size={12} />
          </Link>
        ) : null}
      </div>

      <div className="rcard-foot">
        <span className="chip chip-agency">{agencyName(w.top_agency)}</span>
        <div className="rcard-actions">
          {canEscalate ? (
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => onEscalate(w)} title={t('scorecard.escalateTitle', { ward: fmt.ward(w.ward, w.number) })}>
              <Icon name="send" size={14} /> {t('scorecard.escalateWard')}
            </button>
          ) : null}
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => navigate(mapHref)} title={t('scorecard.showOnMap', { ward: fmt.ward(w.ward, w.number) })}>
            <Icon name="map" size={14} /> {t('nav.map')}
          </button>
        </div>
      </div>
    </li>
  );
}
