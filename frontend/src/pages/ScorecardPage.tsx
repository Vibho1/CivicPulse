import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, type WardRow } from '../api';
import { useApp } from '../context/AppContext';
import { Icon } from '../components/Icon';
import { EmptyState, ErrorState, Skeleton } from '../components/ui';
import { WardEscalationDialog } from '../components/WardEscalation';
import { useI18n } from '../i18n';
import type { MessageKey } from '../i18n/en';
import { downloadText, toCsv } from '../lib/csv';
import { num, pct } from '../lib/format';
import { useAsync } from '../lib/useAsync';

type SortKey = keyof Pick<
  WardRow,
  | 'ward'
  | 'zone'
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

/** Column headers are i18n keys (`scorecard.col.*`), typed so a typo fails the build. */
interface Column {
  key: SortKey;
  label: MessageKey;
  short?: MessageKey;
  align?: 'left' | 'right';
  title?: MessageKey;
}

const COLUMNS: Column[] = [
  { key: 'ward', label: 'scorecard.col.ward', align: 'left' },
  { key: 'total', label: 'scorecard.col.total', title: 'scorecard.col.totalTitle' },
  { key: 'reports', label: 'scorecard.col.reports' },
  { key: 'active', label: 'scorecard.col.active', title: 'scorecard.col.activeTitle' },
  { key: 'open', label: 'scorecard.col.open' },
  { key: 'in_progress', label: 'scorecard.col.inProgress', short: 'scorecard.col.inProgressShort' },
  { key: 'closures', label: 'scorecard.col.closures', title: 'scorecard.col.closuresTitle' },
  { key: 'verified_closure_rate', label: 'scorecard.col.verified', short: 'scorecard.col.verifiedShort', title: 'scorecard.col.verifiedTitle' },
  { key: 'unverified_closure_rate', label: 'scorecard.col.unverified', short: 'scorecard.col.unverifiedShort', title: 'scorecard.col.unverifiedTitle' },
  { key: 'closure_disputed', label: 'scorecard.col.disputed', short: 'scorecard.col.disputedShort', title: 'scorecard.col.disputedTitle' },
  { key: 'avg_hours_to_close', label: 'scorecard.col.avgClose', short: 'scorecard.col.avgCloseShort' },
  { key: 'sla_breach_rate', label: 'scorecard.col.slaBreach', short: 'scorecard.col.slaBreachShort' },
  { key: 'repeat_failure_rate', label: 'scorecard.col.repeat', short: 'scorecard.col.repeatShort' },
  { key: 'top_agency', label: 'scorecard.col.topAgency', align: 'left' },
];

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

function rateTone(v: number | null, invert = false): string {
  if (v === null) return '';
  const bad = invert ? v >= 50 : v < 50;
  const mid = invert ? v >= 25 : v < 75;
  return bad ? 'tone-bad' : mid ? 'tone-warn' : 'tone-good';
}

export default function ScorecardPage() {
  const { dataVersion, meta } = useApp();
  const { t, tx, fmt, label } = useI18n();
  const navigate = useNavigate();
  const q = useAsync(() => api.scorecard(), [dataVersion]);
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'verified_closure_rate', dir: 'asc' });
  const [escalating, setEscalating] = useState<WardRow | null>(null);

  const agencyShort = useMemo(() => new Map((meta?.agencies ?? []).map((a) => [a.id, a.short])), [meta]);
  const rows = useMemo(() => [...(q.data?.wards ?? [])].sort((a, b) => compare(a, b, sort.key, sort.dir)), [q.data, sort]);

  function toggleSort(key: SortKey) {
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'ward' || key === 'zone' || key === 'top_agency' ? 'asc' : key === 'verified_closure_rate' ? 'asc' : 'desc' }));
  }

  const agencyName = (w: WardRow) => label('agency', w.top_agency, agencyShort.get(w.top_agency) ?? w.top_agency);

  /** Escalate button for ward cards and table rows; must not trigger the row's map navigation. */
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
      'lat',
      'lng',
    ];
    const body = rows.map((w) => [
      w.ward,
      w.number,
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
      w.lat,
      w.lng,
    ]);
    const stamp = new Date().toISOString().slice(0, 10);
    downloadText(`civicpulse-ward-scorecard-${stamp}.csv`, toCsv(header, body));
  }

  const city = q.data?.city ?? null;

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
        <button type="button" className="btn btn-secondary" onClick={downloadCsv} disabled={!rows.length}>
          <Icon name="download" size={16} /> {t('scorecard.downloadCsv')}
        </button>
      </header>

      <section className="stats stats-wide" aria-label={t('stats.aria')}>
        {q.loading && !city
          ? Array.from({ length: 9 }, (_, i) => (
              <div key={i} className="stat">
                <Skeleton h={28} w={60} />
                <Skeleton h={12} w={110} />
              </div>
            ))
          : city
            ? [
                { label: t('stats.issues'), value: String(city.clusters) },
                { label: t('stats.reports'), value: String(city.reports) },
                { label: t('stats.active'), value: num(city.active), tone: (city.active ?? 0) > 0 ? 'warn' : '' },
                { label: t('stats.unresolvedShort'), value: String(city.unresolved), tone: city.unresolved > 0 ? 'warn' : '' },
                { label: t('stats.closures'), value: String(city.closures) },
                { label: t('stats.verified'), value: pct(city.verified_closure_rate), tone: city.verified_closure_rate !== null ? (city.verified_closure_rate >= 75 ? 'good' : city.verified_closure_rate >= 50 ? 'warn' : 'bad') : '' },
                { label: t('stats.unverified'), value: pct(city.unverified_closure_rate), tone: (city.unverified_closure_rate ?? 0) >= 50 ? 'bad' : (city.unverified_closure_rate ?? 0) > 0 ? 'warn' : '' },
                { label: t('stats.slaBreached'), value: String(city.sla_breached_open), tone: city.sla_breached_open > 0 ? 'bad' : '' },
                { label: t('stats.repeat'), value: String(city.repeat_failures), tone: city.repeat_failures > 0 ? 'warn' : '' },
              ].map((it) => (
                <div key={it.label} className={`stat${it.tone ? ` stat-${it.tone}` : ''}`}>
                  <div className="stat-value">{it.value}</div>
                  <div className="stat-label">{it.label}</div>
                </div>
              ))
            : null}
      </section>

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
          {/* Phone layout: one card per ward (the wide table is hidden by CSS below 768px). */}
          <ul className="ward-cards" aria-label={t('scorecard.title')}>
            {rows.map((w) => {
              const go = () => navigate(`/?ward=${encodeURIComponent(w.ward)}`);
              return (
                <li key={w.ward} className="card ward-card" onClick={go} onKeyDown={(e) => (e.key === 'Enter' ? go() : undefined)} tabIndex={0} role="link">
                  <div className="ward-card-head">
                    <div>
                      <div className="ward-card-name">{fmt.ward(w.ward, w.number)}</div>
                      <div className="muted small">{t('common.zone', { zone: label('zone', w.zone, w.zone) })}</div>
                    </div>
                    {w.closures ? (
                      <span className={`badge badge-lg ${(w.verified_closure_rate ?? 0) >= 75 ? 'tone-good' : (w.verified_closure_rate ?? 0) >= 50 ? 'tone-warn' : 'tone-bad'}`}>
                        {t('scorecard.card.verified', { value: pct(w.verified_closure_rate) })}
                      </span>
                    ) : (
                      <span className="badge badge-lg tone-neutral">{t('scorecard.card.noClosures')}</span>
                    )}
                  </div>
                  <div className="ward-card-grid">
                    <div>
                      <span className="ward-card-value">{w.total}</span>
                      <span className="ward-card-label">{t('scorecard.col.total')}</span>
                    </div>
                    <div>
                      <span className="ward-card-value">{w.reports}</span>
                      <span className="ward-card-label">{t('scorecard.col.reports')}</span>
                    </div>
                    <div>
                      <span className="ward-card-value">{w.active ?? w.open + w.in_progress}</span>
                      <span className="ward-card-label">{t('scorecard.col.active')}</span>
                    </div>
                    <div>
                      <span className="ward-card-value">{w.closures}</span>
                      <span className="ward-card-label">{t('scorecard.col.closures')}</span>
                    </div>
                    <div>
                      <span className={`ward-card-value${w.closure_disputed ? ' tone-bad' : ''}`}>{w.closure_disputed}</span>
                      <span className="ward-card-label">{t('scorecard.col.disputedShort')}</span>
                    </div>
                    <div>
                      <span className={`ward-card-value${w.sla_breached_open ? ' tone-bad' : ''}`}>{w.sla_breached_open}</span>
                      <span className="ward-card-label">{t('sla.breached')}</span>
                    </div>
                  </div>
                  {w.closures ? (
                    <div className="ward-card-bar">
                      <div className="bar-head">
                        <span className="bar-label">{t('scorecard.col.unverified')}</span>
                        <span className="bar-value">{pct(w.unverified_closure_rate)}</span>
                      </div>
                      <div className="bar-track">
                        <div className="bar-fill bar-fill-bad" style={{ width: `${w.unverified_closure_rate ?? 0}%` }} />
                      </div>
                    </div>
                  ) : null}
                  <div className="chips">
                    <span className={`chip ${(w.sla_breach_rate ?? 0) >= 50 ? 'chip-bad' : 'chip-muted'}`}>{t('scorecard.card.slaBreach', { value: pct(w.sla_breach_rate) })}</span>
                    {(w.repeat_failure_rate ?? 0) > 0 ? <span className="chip chip-warn">{t('scorecard.card.repeat', { value: pct(w.repeat_failure_rate) })}</span> : null}
                    {w.avg_hours_to_close !== null ? <span className="chip chip-muted">{t('scorecard.card.avgClose', { time: fmt.duration(w.avg_hours_to_close) })}</span> : null}
                    <span className="chip chip-agency">{agencyName(w)}</span>
                  </div>
                  {canEscalate(w) ? <div className="ward-card-actions">{escalateButton(w)}</div> : null}
                </li>
              );
            })}
          </ul>

          <div className="card table-card">
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
                    <th scope="row" className="left sticky">
                      {fmt.ward(w.ward, w.number)}
                      <span className="ward-zone">{label('zone', w.zone, w.zone)}</span>
                    </th>
                    <td>{w.total}</td>
                    <td>{w.reports}</td>
                    <td>{num(w.active)}</td>
                    <td>{w.open}</td>
                    <td>{w.in_progress}</td>
                    <td>{w.closures}</td>
                    <td className={rateTone(w.verified_closure_rate)}>{w.closures ? pct(w.verified_closure_rate) : <span className="muted">—</span>}</td>
                    <td className={rateTone(w.unverified_closure_rate, true)}>
                      {w.closures ? (
                        <span className="inline-bar">
                          <span className="inline-bar-track">
                            <span className="inline-bar-fill" style={{ width: `${w.unverified_closure_rate ?? 0}%` }} />
                          </span>
                          {pct(w.unverified_closure_rate)}
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className={w.closure_disputed > 0 ? 'tone-bad' : ''}>{w.closure_disputed}</td>
                    <td>{w.avg_hours_to_close === null ? <span className="muted">—</span> : fmt.duration(w.avg_hours_to_close)}</td>
                    <td className={rateTone(w.sla_breach_rate, true)}>{pct(w.sla_breach_rate)}</td>
                    <td className={(w.repeat_failure_rate ?? 0) > 0 ? 'tone-warn' : ''}>{pct(w.repeat_failure_rate)}</td>
                    <td className="left">
                      <span className="chip chip-agency">{agencyName(w)}</span>
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
        </>
      )}

      {escalating ? <WardEscalationDialog key={escalating.ward} ward={escalating} onClose={() => setEscalating(null)} /> : null}
    </div>
  );
}
