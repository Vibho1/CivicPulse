import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, type WardRow } from '../api';
import { useApp } from '../context/AppContext';
import { Icon } from '../components/Icon';
import { EmptyState, ErrorState, Skeleton } from '../components/ui';
import { downloadText, toCsv } from '../lib/csv';
import { fmtHours, num, pct } from '../lib/format';
import { useAsync } from '../lib/useAsync';

type SortKey = keyof Pick<
  WardRow,
  | 'ward'
  | 'zone'
  | 'total'
  | 'reports'
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

interface Column {
  key: SortKey;
  label: string;
  short?: string;
  align?: 'left' | 'right';
  title?: string;
}

const COLUMNS: Column[] = [
  { key: 'ward', label: 'Ward · zone', align: 'left' },
  { key: 'total', label: 'Issues', title: 'Distinct issue clusters' },
  { key: 'reports', label: 'Reports' },
  { key: 'open', label: 'Open' },
  { key: 'in_progress', label: 'In progress', short: 'In prog.' },
  { key: 'closures', label: 'Closures', title: 'Marked resolved by an official' },
  { key: 'verified_closure_rate', label: 'Verified closures', short: 'Verified %', title: 'Share of closures confirmed by a citizen photo' },
  { key: 'unverified_closure_rate', label: 'Unverified closures', short: 'Unverified %', title: 'Closed on paper only (awaiting proof or disputed)' },
  { key: 'closure_disputed', label: 'Disputed' },
  { key: 'avg_hours_to_close', label: 'Avg time to close', short: 'Avg close' },
  { key: 'sla_breach_rate', label: 'SLA breach', short: 'SLA breach %' },
  { key: 'repeat_failure_rate', label: 'Repeat failures', short: 'Repeat %' },
  { key: 'top_agency', label: 'Top agency', align: 'left' },
];

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
  const navigate = useNavigate();
  const q = useAsync(() => api.scorecard(), [dataVersion]);
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'verified_closure_rate', dir: 'asc' });

  const agencyShort = useMemo(() => new Map((meta?.agencies ?? []).map((a) => [a.id, a.short])), [meta]);
  const rows = useMemo(() => [...(q.data?.wards ?? [])].sort((a, b) => compare(a, b, sort.key, sort.dir)), [q.data, sort]);

  function toggleSort(key: SortKey) {
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'ward' || key === 'zone' || key === 'top_agency' ? 'asc' : key === 'verified_closure_rate' ? 'asc' : 'desc' }));
  }

  function downloadCsv() {
    const header = [
      'ward',
      'zone',
      'issues',
      'reports',
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
      w.zone,
      w.total,
      w.reports,
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
          <h1>Ward scorecard</h1>
          <p className="muted">
            <strong>Verified</strong> = a citizen photo confirmed the fix. <strong>Unverified</strong> = closed on paper only. Worst verified-closure rate first.
          </p>
        </div>
        <button type="button" className="btn btn-secondary" onClick={downloadCsv} disabled={!rows.length}>
          <Icon name="download" size={16} /> Download CSV
        </button>
      </header>

      <section className="stats stats-wide" aria-label="City summary">
        {q.loading && !city
          ? Array.from({ length: 8 }, (_, i) => (
              <div key={i} className="stat">
                <Skeleton h={28} w={60} />
                <Skeleton h={12} w={110} />
              </div>
            ))
          : city
            ? [
                { label: 'Issues', value: String(city.clusters) },
                { label: 'Reports', value: String(city.reports) },
                { label: 'Unresolved', value: String(city.unresolved), tone: city.unresolved > 0 ? 'warn' : '' },
                { label: 'Closures', value: String(city.closures) },
                { label: 'Verified closures', value: pct(city.verified_closure_rate), tone: city.verified_closure_rate !== null ? (city.verified_closure_rate >= 75 ? 'good' : city.verified_closure_rate >= 50 ? 'warn' : 'bad') : '' },
                { label: 'Unverified closures', value: pct(city.unverified_closure_rate), tone: (city.unverified_closure_rate ?? 0) >= 50 ? 'bad' : (city.unverified_closure_rate ?? 0) > 0 ? 'warn' : '' },
                { label: 'SLA-breached open', value: String(city.sla_breached_open), tone: city.sla_breached_open > 0 ? 'bad' : '' },
                { label: 'Repeat failures', value: String(city.repeat_failures), tone: city.repeat_failures > 0 ? 'warn' : '' },
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
          <EmptyState title="No wards to score yet" body="Seed demo data from the Demo menu, or file a report." icon="bar-chart">
            <button type="button" className="btn btn-primary" onClick={() => navigate('/report')}>
              <Icon name="plus-circle" size={16} /> Report an issue
            </button>
          </EmptyState>
        </div>
      ) : (
        <>
          {/* Phone layout: one card per ward (the 14-column table is hidden by CSS below 768px). */}
          <ul className="ward-cards" aria-label="Ward scorecard">
            {rows.map((w) => {
              const go = () => navigate(`/?ward=${encodeURIComponent(w.ward)}`);
              return (
                <li key={w.ward} className="card ward-card" onClick={go} onKeyDown={(e) => (e.key === 'Enter' ? go() : undefined)} tabIndex={0} role="link">
                  <div className="ward-card-head">
                    <div>
                      <div className="ward-card-name">{w.ward}</div>
                      <div className="muted small">{w.zone} zone</div>
                    </div>
                    {w.closures ? (
                      <span className={`badge badge-lg ${(w.verified_closure_rate ?? 0) >= 75 ? 'tone-good' : (w.verified_closure_rate ?? 0) >= 50 ? 'tone-warn' : 'tone-bad'}`}>
                        {pct(w.verified_closure_rate)} verified
                      </span>
                    ) : (
                      <span className="badge badge-lg tone-neutral">No closures yet</span>
                    )}
                  </div>
                  <div className="ward-card-grid">
                    <div>
                      <span className="ward-card-value">{w.total}</span>
                      <span className="ward-card-label">Issues</span>
                    </div>
                    <div>
                      <span className="ward-card-value">{w.reports}</span>
                      <span className="ward-card-label">Reports</span>
                    </div>
                    <div>
                      <span className="ward-card-value">{w.open + w.in_progress}</span>
                      <span className="ward-card-label">Open</span>
                    </div>
                    <div>
                      <span className="ward-card-value">{w.closures}</span>
                      <span className="ward-card-label">Closures</span>
                    </div>
                    <div>
                      <span className={`ward-card-value${w.closure_disputed ? ' tone-bad' : ''}`}>{w.closure_disputed}</span>
                      <span className="ward-card-label">Disputed</span>
                    </div>
                  </div>
                  {w.closures ? (
                    <div className="ward-card-bar">
                      <div className="bar-head">
                        <span className="bar-label">Unverified closures</span>
                        <span className="bar-value">{pct(w.unverified_closure_rate)}</span>
                      </div>
                      <div className="bar-track">
                        <div className="bar-fill bar-fill-bad" style={{ width: `${w.unverified_closure_rate ?? 0}%` }} />
                      </div>
                    </div>
                  ) : null}
                  <div className="chips">
                    <span className={`chip ${(w.sla_breach_rate ?? 0) >= 50 ? 'chip-bad' : 'chip-muted'}`}>SLA breach {pct(w.sla_breach_rate)}</span>
                    {(w.repeat_failure_rate ?? 0) > 0 ? <span className="chip chip-warn">Repeat {pct(w.repeat_failure_rate)}</span> : null}
                    {w.avg_hours_to_close !== null ? <span className="chip chip-muted">Avg close {fmtHours(w.avg_hours_to_close)}</span> : null}
                    <span className="chip chip-agency">{agencyShort.get(w.top_agency) ?? w.top_agency}</span>
                  </div>
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
                      <th key={col.key} scope="col" className={col.align === 'left' ? 'left' : 'right'} aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'} title={col.title}>
                        <button type="button" className={`th-btn${active ? ' active' : ''}`} onClick={() => toggleSort(col.key)}>
                          <span className="th-long">{col.label}</span>
                          <span className="th-short">{col.short ?? col.label}</span>
                          <span className="sort-ind" aria-hidden="true">
                            {active ? (sort.dir === 'asc' ? '▲' : '▼') : ''}
                          </span>
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((w) => (
                  <tr key={w.ward} className="clickable" onClick={() => navigate(`/?ward=${encodeURIComponent(w.ward)}`)} tabIndex={0} onKeyDown={(e) => (e.key === 'Enter' ? navigate(`/?ward=${encodeURIComponent(w.ward)}`) : undefined)} title={`Show ${w.ward} on the map`}>
                    <th scope="row" className="left sticky">
                      {w.ward}
                      <span className="ward-zone">{w.zone}</span>
                    </th>
                    <td>{w.total}</td>
                    <td>{w.reports}</td>
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
                    <td>{w.avg_hours_to_close === null ? <span className="muted">—</span> : fmtHours(w.avg_hours_to_close)}</td>
                    <td className={rateTone(w.sla_breach_rate, true)}>{pct(w.sla_breach_rate)}</td>
                    <td className={(w.repeat_failure_rate ?? 0) > 0 ? 'tone-warn' : ''}>{pct(w.repeat_failure_rate)}</td>
                    <td className="left">
                      <span className="chip chip-agency">{agencyShort.get(w.top_agency) ?? w.top_agency}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small table-foot">
            {rows.length} wards with activity · avg open impact across the city {num(rows.reduce((s, w) => s + w.avg_open_impact * (w.open + w.in_progress + w.closure_disputed), 0) / Math.max(1, rows.reduce((s, w) => s + w.open + w.in_progress + w.closure_disputed, 0)), 1)} · tap a row to see the ward on the map.
          </p>
        </div>
        </>
      )}
    </div>
  );
}
