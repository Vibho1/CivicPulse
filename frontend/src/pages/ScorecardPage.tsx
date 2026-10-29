import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api, type WardRow } from '../api';
import { useApp } from '../context/AppContext';
import { Icon } from '../components/Icon';
import { EmptyState, ErrorState, Skeleton } from '../components/ui';
import { WardEscalationDialog } from '../components/WardEscalation';
import { FunnelStrip } from '../components/scorecard/FunnelStrip';
import { Bullet, GradeBadge, MixBar, MixLegend } from '../components/scorecard/primitives';
import { WardReportCard } from '../components/scorecard/WardReportCard';
import { useI18n } from '../i18n';
import type { MessageKey } from '../i18n/en';
import { downloadText, toCsv } from '../lib/csv';
import { num, pct } from '../lib/format';
import { useAsync } from '../lib/useAsync';

type SortKey = keyof Pick<
  WardRow,
  | 'rank'
  | 'ward'
  | 'zone'
  | 'grade'
  | 'accountability_index'
  | 'total'
  | 'reports'
  | 'active'
  | 'open'
  | 'in_progress'
  | 'closures'
  | 'verified_closure_rate'
  | 'unverified_closure_rate'
  | 'closure_disputed'
  | 'avg_hours_to_close'
  | 'sla_breach_rate'
  | 'repeat_failure_rate'
  | 'top_agency'
>;

type View = 'cards' | 'table';
const VIEW_KEY = 'cp.scorecard.view';

/** Column headers are i18n keys (`scorecard.col.*`), typed so a typo fails the build. */
interface Column {
  key: SortKey;
  label: MessageKey;
  short?: MessageKey;
  align?: 'left' | 'right';
  title?: MessageKey;
}

const COLUMNS: Column[] = [
  { key: 'rank', label: 'scorecard.col.rank', title: 'scorecard.col.rankTitle' },
  { key: 'ward', label: 'scorecard.col.ward', align: 'left' },
  { key: 'accountability_index', label: 'scorecard.col.grade', title: 'scorecard.col.gradeTitle' },
  { key: 'total', label: 'scorecard.col.total', title: 'scorecard.col.totalTitle' },
  { key: 'reports', label: 'scorecard.col.reports' },
  { key: 'active', label: 'scorecard.col.active', title: 'scorecard.col.activeTitle' },
  { key: 'closures', label: 'scorecard.col.closures', title: 'scorecard.col.closuresTitle' },
  { key: 'verified_closure_rate', label: 'scorecard.col.verified', short: 'scorecard.col.verifiedShort', title: 'scorecard.col.verifiedTitle', align: 'left' },
  { key: 'closure_disputed', label: 'scorecard.col.disputed', short: 'scorecard.col.disputedShort', title: 'scorecard.col.disputedTitle' },
  { key: 'sla_breach_rate', label: 'scorecard.col.slaBreach', short: 'scorecard.col.slaBreachShort', align: 'left' },
  { key: 'avg_hours_to_close', label: 'scorecard.col.avgClose', short: 'scorecard.col.avgCloseShort' },
  { key: 'repeat_failure_rate', label: 'scorecard.col.repeat', short: 'scorecard.col.repeatShort' },
  { key: 'top_agency', label: 'scorecard.col.topAgency', align: 'left' },
];

const VERIFIED_TARGET = 75;
const SLA_TARGET = 0;

/** Wards with something to escalate: Unverified closures or SLA-breached open issues. */
function canEscalate(w: WardRow): boolean {
  return w.closure_disputed > 0 || w.sla_breached_open > 0;
}

function compare(a: WardRow, b: WardRow, key: SortKey, dir: 'asc' | 'desc'): number {
  const av = a[key];
  const bv = b[key];
  // nulls (no closures yet) always sink to the bottom regardless of direction
  if (av === null || av === undefined) return bv === null || bv === undefined ? 0 : 1;
  if (bv === null || bv === undefined) return -1;
  let r: number;
  if (typeof av === 'string' && typeof bv === 'string') r = av.localeCompare(bv);
  else r = Number(av) - Number(bv);
  return dir === 'asc' ? r : -r;
}

function readView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === 'table' ? 'table' : 'cards';
  } catch {
    return 'cards';
  }
}

export default function ScorecardPage() {
  const { dataVersion, meta } = useApp();
  const { t, tx, fmt, label } = useI18n();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const q = useAsync(() => api.scorecard(), [dataVersion]);
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'rank', dir: 'asc' });
  const [escalating, setEscalating] = useState<WardRow | null>(null);
  const urlView = searchParams.get('view');
  const [view, setViewState] = useState<View>(() => (urlView === 'table' || urlView === 'cards' ? urlView : readView()));

  function setView(next: View) {
    setViewState(next);
    const sp = new URLSearchParams(searchParams);
    sp.set('view', next);
    setSearchParams(sp, { replace: true });
  }

  useEffect(() => {
    try {
      localStorage.setItem(VIEW_KEY, view);
    } catch {
      /* private mode */
    }
  }, [view]);

  const agencyShort = useMemo(() => new Map<string, string>((meta?.agencies ?? []).map((a) => [a.id, a.short])), [meta]);
  const rows = useMemo(() => [...(q.data?.wards ?? [])].sort((a, b) => compare(a, b, sort.key, sort.dir)), [q.data, sort]);

  function toggleSort(key: SortKey) {
    setSort((s) => {
      if (s.key === key) return { key, dir: s.dir === 'asc' ? 'desc' : 'asc' };
      const ascFirst: SortKey[] = ['rank', 'ward', 'zone', 'top_agency', 'accountability_index', 'verified_closure_rate'];
      return { key, dir: ascFirst.includes(key) ? 'asc' : 'desc' };
    });
  }

  const agencyName = (id: string) => label('agency', id, agencyShort.get(id) ?? id);

  /** Escalate button for table rows; must not trigger the row's map navigation. */
  function escalateButton(w: WardRow) {
    return (
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        onClick={(e) => {
          e.stopPropagation();
          setEscalating(w);
        }}
        onKeyDown={(e) => e.stopPropagation()}
        title={t('scorecard.escalateTitle', { ward: fmt.ward(w.ward, w.number) })}
      >
        <Icon name="send" size={14} /> {t('scorecard.escalate')}
      </button>
    );
  }

  function downloadCsv() {
    const header = [
      'rank',
      'grade',
      'accountability_index',
      'ward',
      'ward_number',
      'zone',
      'issues',
      'reports',
      'active',
      'open',
      'in_progress',
      'resolved_pending_verification',
      'resolved_verified',
      'closure_disputed',
      'closures',
      'verified_closure_rate_pct',
      'unverified_closure_rate_pct',
      'disputed_closure_rate_pct',
      'avg_hours_to_close',
      'avg_hours_to_verified_fix',
      'sla_breach_rate_pct',
      'sla_breached_open',
      'repeat_failure_rate_pct',
      'avg_open_impact',
      'top_agency',
      'top_problem_cluster',
      'top_problem_kind',
      'lat',
      'lng',
    ];
    const body = rows.map((w) => [
      w.rank,
      w.grade,
      w.accountability_index,
      w.ward,
      w.number ?? '',
      w.zone,
      w.total,
      w.reports,
      w.active,
      w.open,
      w.in_progress,
      w.resolved_pending_verification,
      w.resolved_verified,
      w.closure_disputed,
      w.closures,
      w.verified_closure_rate,
      w.unverified_closure_rate,
      w.disputed_closure_rate,
      w.avg_hours_to_close,
      w.avg_hours_to_verified_fix,
      w.sla_breach_rate,
      w.sla_breached_open,
      w.repeat_failure_rate,
      w.avg_open_impact,
      w.top_agency,
      w.top_problem?.cluster_id ?? '',
      w.top_problem?.kind ?? '',
      w.lat,
      w.lng,
    ]);
    const stamp = new Date().toISOString().slice(0, 10);
    downloadText(`civicpulse-ward-scorecard-${stamp}.csv`, toCsv(header, body));
  }

  const city = q.data?.city ?? null;
  const gd = city?.grade_distribution;

  return (
    <div className="page">
      <header className="page-head row between wrap">
        <div>
          <h1>{t('scorecard.title')}</h1>
          <p className="muted">
            {tx('scorecard.subtitle', {
              verified: <strong>{t('status.resolved_verified')}</strong>,
              pending: <strong>{t('status.resolved_pending_verification')}</strong>,
              unverified: <strong>{t('status.closure_disputed')}</strong>,
            })}
          </p>
        </div>
        <div className="row gap-s wrap">
          <div className="segmented" role="tablist" aria-label={t('scorecard.view.aria')}>
            <button type="button" role="tab" aria-selected={view === 'cards'} className={`segmented-btn${view === 'cards' ? ' active' : ''}`} onClick={() => setView('cards')}>
              <Icon name="activity" size={14} /> {t('scorecard.view.cards')}
            </button>
            <button type="button" role="tab" aria-selected={view === 'table'} className={`segmented-btn${view === 'table' ? ' active' : ''}`} onClick={() => setView('table')}>
              <Icon name="bar-chart" size={14} /> {t('scorecard.view.table')}
            </button>
          </div>
          <button type="button" className="btn btn-secondary" onClick={downloadCsv} disabled={!rows.length}>
            <Icon name="download" size={16} /> {t('scorecard.downloadCsv')}
          </button>
        </div>
      </header>

      {q.loading && !city ? (
        <div className="card">
          <Skeleton h={190} />
        </div>
      ) : city ? (
        <FunnelStrip city={city} />
      ) : null}

      {q.error && !q.data ? (
        <ErrorState message={q.error} onRetry={q.reload} />
      ) : q.loading && !q.data ? (
        <div className="card">
          <Skeleton h={240} />
        </div>
      ) : rows.length === 0 ? (
        <div className="card">
          <EmptyState title={t('scorecard.empty')} body={t('scorecard.emptyBody')} icon="bar-chart">
            <button type="button" className="btn btn-primary" onClick={() => navigate('/report')}>
              <Icon name="plus-circle" size={16} /> {t('report.title')}
            </button>
          </EmptyState>
        </div>
      ) : (
        <>
          <div className="row between wrap scorecard-meta">
            <span className="muted small">
              {gd ? t('scorecard.gradeDist', { a: gd.A, b: gd.B, c: gd.C, d: gd.D, f: gd.F }) : null}
              {' · '}
              {t('scorecard.index.hint')}
            </span>
            <MixLegend />
          </div>

          {view === 'cards' ? (
            <ul className="report-cards" aria-label={t('scorecard.title')}>
              {rows.map((w) => (
                <WardReportCard key={w.ward} w={w} agencyName={agencyName} canEscalate={canEscalate(w)} onEscalate={setEscalating} />
              ))}
            </ul>
          ) : (
            <div className="card table-card table-card-always">
              <div className="table-wrap">
                <table className="table scorecard">
                  <thead>
                    <tr>
                      {COLUMNS.map((col) => {
                        const active = sort.key === col.key;
                        return (
                          <th key={col.key} scope="col" className={col.align === 'left' ? 'left' : 'right'} aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'} title={col.title ? t(col.title) : undefined}>
                            <button type="button" className={`th-btn${active ? ' active' : ''}`} onClick={() => toggleSort(col.key)}>
                              <span className="th-long">{t(col.label)}</span>
                              <span className="th-short">{t(col.short ?? col.label)}</span>
                              <span className="sort-ind" aria-hidden="true">
                                {active ? (sort.dir === 'asc' ? '▲' : '▼') : ''}
                              </span>
                            </button>
                          </th>
                        );
                      })}
                      <th scope="col" className="left">
                        <span className="sr-only">{t('scorecard.actions')}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((w) => (
                      <tr
                        key={w.ward}
                        className="clickable"
                        onClick={() => navigate(`/?ward=${encodeURIComponent(w.ward)}`)}
                        tabIndex={0}
                        onKeyDown={(e) => (e.key === 'Enter' ? navigate(`/?ward=${encodeURIComponent(w.ward)}`) : undefined)}
                        title={t('scorecard.showOnMap', { ward: fmt.ward(w.ward, w.number) })}
                      >
                        <td className={`rank-cell rank-${w.grade}`}>
                          <span className="rank">{w.rank}</span>
                        </td>
                        <th scope="row" className="left sticky">
                          {fmt.ward(w.ward, w.number)}
                          <span className="ward-zone">{label('zone', w.zone, w.zone)}</span>
                          <MixBar w={w} height={6} />
                        </th>
                        <td>
                          <span className="grade-cell">
                            <GradeBadge grade={w.grade} index={w.accountability_index} size="sm" lowData={w.low_data} />
                            <span className="muted small">{num(w.accountability_index)}</span>
                          </span>
                        </td>
                        <td>{w.total}</td>
                        <td>{w.reports}</td>
                        <td>{num(w.active)}</td>
                        <td>{w.closures}</td>
                        <td className="left">
                          <Bullet value={w.closures ? w.verified_closure_rate : null} target={VERIFIED_TARGET} caption={w.closures ? t('scorecard.bullet.ofClosures', { value: pct(w.verified_closure_rate), count: w.closures }) : undefined} />
                        </td>
                        <td className={w.closure_disputed > 0 ? 'tone-bad' : ''}>{w.closure_disputed}</td>
                        <td className="left">
                          <Bullet value={w.sla_breach_rate} target={SLA_TARGET} invert />
                        </td>
                        <td>{w.avg_hours_to_close === null ? <span className="muted">—</span> : fmt.duration(w.avg_hours_to_close)}</td>
                        <td className={(w.repeat_failure_rate ?? 0) > 0 ? 'tone-warn' : ''}>{pct(w.repeat_failure_rate)}</td>
                        <td className="left">
                          <span className="chip chip-agency">{agencyName(w.top_agency)}</span>
                        </td>
                        <td className="left">{canEscalate(w) ? escalateButton(w) : null}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted small table-foot">
                {t('scorecard.footer', {
                  wards: fmt.count('ward', rows.length),
                  impact: num(rows.reduce((s, w) => s + w.avg_open_impact * (w.open + w.in_progress + w.closure_disputed), 0) / Math.max(1, rows.reduce((s, w) => s + w.open + w.in_progress + w.closure_disputed, 0)), 1),
                })}
              </p>
            </div>
          )}
        </>
      )}

      {escalating ? <WardEscalationDialog key={escalating.ward} ward={escalating} onClose={() => setEscalating(null)} /> : null}
    </div>
  );
}
