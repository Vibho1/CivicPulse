import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { AttributionControl, CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet';
import { latLngBounds, type CircleMarker as LeafletCircleMarker } from 'leaflet';
import { ALL_STATUSES, api, isClusterStatus, type CityStats, type Cluster, type ClusterStatus } from '../api';
import { useApp } from '../context/AppContext';
import { useI18n } from '../i18n';
import { BENGALURU_CENTER, BENGALURU_ZOOM } from '../lib/geo';
import { pct } from '../lib/format';
import { STATUS_COLORS, STATUS_SHORT, normalizeCategory } from '../lib/status';
import { useAsync } from '../lib/useAsync';
import { Icon } from '../components/Icon';
import { AgencyChip, EmptyState, ErrorState, ScoreRing, Skeleton, SlaBadge, StatusBadge } from '../components/ui';

const OSM_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function markerRadius(score: number): number {
  return 7 + (Math.max(0, Math.min(100, score)) / 100) * 15; // 7–22 px
}

/** Keeps Leaflet sized correctly and fits the view when the ward filter changes. */
function MapController({ clusters, fitKey, focus }: { clusters: Cluster[]; fitKey: string; focus: Cluster | null }) {
  const map = useMap();
  const lastFit = useRef<string | null>(null);

  useEffect(() => {
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(map.getContainer());
    return () => ro.disconnect();
  }, [map]);

  useEffect(() => {
    if (lastFit.current === fitKey) return;
    if (!fitKey) {
      if (lastFit.current !== null) map.setView(BENGALURU_CENTER, BENGALURU_ZOOM);
      lastFit.current = fitKey;
      return;
    }
    if (!clusters.length) return;
    lastFit.current = fitKey;
    const b = latLngBounds(clusters.map((c) => [c.lat, c.lng] as [number, number]));
    map.fitBounds(b, { padding: [48, 48], maxZoom: 15 });
  }, [map, clusters, fitKey]);

  useEffect(() => {
    if (focus) map.flyTo([focus.lat, focus.lng], Math.max(map.getZoom(), 16), { duration: 0.8 });
  }, [map, focus]);

  return null;
}

function StatsStrip({ stats, loading }: { stats: CityStats | null; loading: boolean }) {
  const { meta } = useApp();
  const { t } = useI18n();
  const repeatDays = meta?.repeat_failure_window_days ?? 180;
  const items: { label: string; value: string; tone?: string; hint: string }[] = stats
    ? [
        { label: t('stats.unresolved'), value: String(stats.unresolved), hint: t('stats.unresolvedHint') },
        { label: t('stats.closures'), value: String(stats.closures), hint: t('stats.closuresHint') },
        {
          label: t('stats.unverified'),
          value: pct(stats.unverified_closure_rate),
          tone: (stats.unverified_closure_rate ?? 0) >= 50 ? 'bad' : 'warn',
          hint: t('stats.unverifiedHint'),
        },
        { label: t('stats.slaBreached'), value: String(stats.sla_breached_open), tone: stats.sla_breached_open > 0 ? 'bad' : undefined, hint: t('stats.slaBreachedHint') },
        { label: t('stats.repeat'), value: String(stats.repeat_failures), tone: stats.repeat_failures > 0 ? 'warn' : undefined, hint: t('stats.repeatHint', { days: repeatDays }) },
      ]
    : [];
  return (
    <section className="stats" aria-label={t('stats.aria')}>
      {loading && !stats
        ? Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="stat">
              <Skeleton h={28} w={60} />
              <Skeleton h={12} w={110} />
            </div>
          ))
        : items.map((it) => (
            <div key={it.label} className={`stat${it.tone ? ` stat-${it.tone}` : ''}`} title={it.hint}>
              <div className="stat-value">{it.value}</div>
              <div className="stat-label">{it.label}</div>
            </div>
          ))}
    </section>
  );
}

function IssueRow({ cluster, onLocate }: { cluster: Cluster; onLocate: (c: Cluster) => void }) {
  const { t, fmt, label } = useI18n();
  return (
    <li className={`issue-row${cluster.repeat_failure ? ' repeat' : ''}`}>
      <Link to={`/clusters/${cluster.id}`} className="issue-main">
        <ScoreRing score={cluster.impact_score} size={48} stroke={5} />
        <div className="issue-text">
          <div className="issue-title">{cluster.title}</div>
          <div className="issue-sub">
            <Icon name="pin" size={12} /> {fmt.ward(cluster.ward)}
            {cluster.zone ? <span className="muted"> · {label('zone', cluster.zone, cluster.zone)}</span> : null}
            <span className="muted"> · {fmt.count('report', cluster.report_count)}</span>
            <span className="muted"> · {fmt.timeAgo(cluster.created_at)}</span>
          </div>
          <div className="issue-chips">
            <StatusBadge status={cluster.status} short size="sm" />
            <AgencyChip agency={cluster.agency} short={cluster.agency_short} label={cluster.agency_label} reason={cluster.agency_reason} />
            <SlaBadge cluster={cluster} />
            {cluster.repeat_failure ? (
              <span className="chip chip-bad">
                <Icon name="flag" size={12} /> {t('common.repeatFailure')}
              </span>
            ) : null}
          </div>
        </div>
      </Link>
      <button type="button" className="icon-btn locate" onClick={() => onLocate(cluster)} aria-label={t('map.locateAria', { title: cluster.title })} title={t('map.locate')}>
        <Icon name="crosshair" size={18} />
      </button>
    </li>
  );
}

export default function MapPage() {
  const { meta, dataVersion } = useApp();
  const { t, tx, fmt, label } = useI18n();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const ward = searchParams.get('ward') ?? '';
  // Old links may still carry pre-PRD category ids (e.g. 'garbage').
  const category = normalizeCategory(searchParams.get('category') ?? '');
  const statusParam = searchParams.get('status') ?? '';
  const statuses = useMemo(() => statusParam.split(',').filter(isClusterStatus), [statusParam]);
  const slaOnly = searchParams.get('sla') === 'breached';

  const clustersQ = useAsync(
    () => api.clusters({ status: statuses, ward, category, sla_breached: slaOnly || undefined, limit: 500 }),
    [statusParam, ward, category, slaOnly, dataVersion],
  );
  const statsQ = useAsync(() => api.stats(), [dataVersion]);

  const [focus, setFocus] = useState<Cluster | null>(null);
  const markerRefs = useRef(new Map<string, LeafletCircleMarker>());

  const clusters = useMemo(() => [...(clustersQ.data?.clusters ?? [])].sort((a, b) => b.impact_score - a.impact_score), [clustersQ.data]);

  const wardOptions = useMemo(() => {
    const names = new Set<string>((meta?.wards ?? []).map((w) => w.name));
    for (const c of clusters) names.add(c.ward);
    if (ward) names.add(ward);
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [meta, clusters, ward]);

  const categories = meta?.categories ?? [];
  const prdCategories = categories.filter((c) => c.prd);
  const otherCategories = categories.filter((c) => !c.prd);

  function updateParams(mutate: (p: URLSearchParams) => void) {
    const next = new URLSearchParams(searchParams);
    mutate(next);
    setSearchParams(next, { replace: true });
  }

  function toggleStatus(s: ClusterStatus) {
    const set = new Set(statuses);
    if (set.has(s)) set.delete(s);
    else set.add(s);
    updateParams((p) => {
      const list = ALL_STATUSES.filter((x) => set.has(x));
      if (list.length && list.length < ALL_STATUSES.length) p.set('status', list.join(','));
      else p.delete('status');
    });
  }

  function toggleSla() {
    updateParams((p) => (slaOnly ? p.delete('sla') : p.set('sla', 'breached')));
  }

  function locate(c: Cluster) {
    setFocus(c);
    window.setTimeout(() => markerRefs.current.get(c.id)?.openPopup(), 900);
    if (window.innerWidth < 960) document.getElementById('live-map')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  const hasFilters = Boolean(ward || category || statuses.length || slaOnly);
  const fitKey = ward ? `ward:${ward}` : '';

  return (
    <div className="page map-page">
      <StatsStrip stats={statsQ.data} loading={statsQ.loading} />

      <div className="map-layout">
        <section className="map-panel card" aria-label={t('map.aria')}>
          <div className="filters">
            <div className="chips status-filter" role="group" aria-label={t('map.filterStatus')}>
              {ALL_STATUSES.map((s) => {
                const active = statuses.length === 0 || statuses.includes(s);
                return (
                  <button
                    key={s}
                    type="button"
                    className={`chip chip-toggle status-${s}${active ? ' active' : ''}`}
                    aria-pressed={statuses.includes(s)}
                    onClick={() => toggleStatus(s)}
                    title={t(`statusHint.${s}`)}
                  >
                    <span className="dot" aria-hidden="true" />
                    {label('statusShort', s, STATUS_SHORT[s])}
                  </button>
                );
              })}
              <span className="filter-sep" aria-hidden="true" />
              <button type="button" className={`chip chip-toggle chip-sla${slaOnly ? ' active' : ''}`} aria-pressed={slaOnly} onClick={toggleSla} title={t('map.slaBreachedTitle')}>
                <Icon name="clock" size={13} /> {t('map.slaBreached')}
              </button>
            </div>
            <div className="filter-selects">
              <select className="select" aria-label={t('map.category')} value={category} onChange={(e) => updateParams((p) => (e.target.value ? p.set('category', e.target.value) : p.delete('category')))}>
                <option value="">{t('map.allCategories')}</option>
                {prdCategories.length ? (
                  <>
                    <optgroup label={t('map.categoryGroupPrd')}>
                      {prdCategories.map((c) => (
                        <option key={c.id} value={c.id}>
                          {label('category', c.id, c.label)}
                        </option>
                      ))}
                    </optgroup>
                    <optgroup label={t('map.categoryGroupMore')}>
                      {otherCategories.map((c) => (
                        <option key={c.id} value={c.id}>
                          {label('category', c.id, c.label)}
                        </option>
                      ))}
                    </optgroup>
                  </>
                ) : (
                  categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {label('category', c.id, c.label)}
                    </option>
                  ))
                )}
              </select>
              <select className="select" aria-label={t('map.ward')} value={ward} onChange={(e) => updateParams((p) => (e.target.value ? p.set('ward', e.target.value) : p.delete('ward')))}>
                <option value="">{t('map.allWards')}</option>
                {wardOptions.map((w) => (
                  <option key={w} value={w}>
                    {fmt.ward(w)}
                  </option>
                ))}
              </select>
              {hasFilters ? (
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSearchParams({}, { replace: true })} aria-label={t('map.clearFilters')}>
                  <Icon name="x" size={14} /> <span className="hide-sm">{t('map.clear')}</span>
                </button>
              ) : null}
            </div>
          </div>

          <div className="map-wrap" id="live-map">
            <MapContainer center={BENGALURU_CENTER} zoom={BENGALURU_ZOOM} scrollWheelZoom attributionControl={false} className="map">
              <TileLayer attribution={OSM_ATTR} url={OSM_URL} maxZoom={19} />
              <AttributionControl position="topright" prefix={false} />
              <MapController clusters={clusters} fitKey={fitKey} focus={focus} />
              {clusters.map((c) => {
                const color = STATUS_COLORS[c.status];
                const r = markerRadius(c.impact_score);
                return (
                  <Fragment key={c.id}>
                    {c.repeat_failure ? (
                      <CircleMarker center={[c.lat, c.lng]} radius={r + 6} interactive={false} pathOptions={{ color: '#dc2626', weight: 2, dashArray: '5 5', fill: false }} />
                    ) : null}
                    <CircleMarker
                      center={[c.lat, c.lng]}
                      radius={r}
                      pathOptions={{ color, weight: 2, fillColor: color, fillOpacity: 0.55 }}
                      ref={(m) => {
                        if (m) markerRefs.current.set(c.id, m);
                        else markerRefs.current.delete(c.id);
                      }}
                    >
                      <Popup>
                        <div className="popup">
                          <div className="popup-title">{c.title}</div>
                          <div className="popup-row">
                            <StatusBadge status={c.status} size="sm" />
                            {c.repeat_failure ? <span className="chip chip-bad">{t('common.repeatFailure')}</span> : null}
                          </div>
                          <div className="popup-row muted">
                            {tx('map.popupImpact', { score: <strong>{Math.round(c.impact_score)}</strong> })} · {fmt.count('report', c.report_count)} · {label('agency', c.agency, c.agency_short)}
                          </div>
                          <div className="popup-row muted">
                            {fmt.ward(c.ward)}
                            {c.landmark ? ` · ${c.landmark}` : ''}
                          </div>
                          <Link to={`/clusters/${c.id}`} className="btn btn-primary btn-sm popup-btn">
                            {t('common.open')} <Icon name="chevron-right" size={14} />
                          </Link>
                        </div>
                      </Popup>
                    </CircleMarker>
                  </Fragment>
                );
              })}
            </MapContainer>

            <div className="legend" aria-label={t('map.legend')}>
              {ALL_STATUSES.map((s) => (
                <span key={s} className="legend-item">
                  <span className="legend-dot" style={{ background: STATUS_COLORS[s] }} /> {label('statusShort', s, STATUS_SHORT[s])}
                </span>
              ))}
              <span className="legend-item">
                <span className="legend-dot legend-repeat" /> {t('common.repeatFailure')}
              </span>
              <span className="legend-item muted">{t('map.legendSize')}</span>
            </div>
            {clustersQ.loading && clusters.length > 0 ? <div className="map-loading">{t('common.updating')}</div> : null}
          </div>
        </section>

        <aside className="side card" aria-label={t('map.topIssues')}>
          <div className="side-head">
            <h2>
              {t('map.topIssues')} <span className="count">{clusters.length}</span>
            </h2>
            <span className="muted small">{t('map.ranked')}</span>
          </div>

          {clustersQ.error && !clustersQ.data ? (
            <ErrorState message={clustersQ.error} onRetry={clustersQ.reload} />
          ) : clustersQ.loading && !clustersQ.data ? (
            <ul className="issue-list">
              {Array.from({ length: 5 }, (_, i) => (
                <li key={i} className="issue-row">
                  <Skeleton h={48} w={48} r={24} />
                  <div className="issue-text">
                    <Skeleton h={14} w="80%" />
                    <Skeleton h={12} w="55%" />
                    <Skeleton h={20} w="70%" />
                  </div>
                </li>
              ))}
            </ul>
          ) : clusters.length === 0 ? (
            <EmptyState title={hasFilters ? t('map.emptyFiltered') : t('map.empty')} body={hasFilters ? t('map.emptyFilteredBody') : t('map.emptyBody')}>
              {hasFilters ? (
                <button type="button" className="btn btn-ghost" onClick={() => setSearchParams({}, { replace: true })}>
                  {t('map.clearFilters')}
                </button>
              ) : null}
              <button type="button" className="btn btn-primary" onClick={() => navigate('/report')}>
                <Icon name="plus-circle" size={16} /> {t('report.title')}
              </button>
            </EmptyState>
          ) : (
            <ul className="issue-list">
              {clusters.slice(0, 60).map((c) => (
                <IssueRow key={c.id} cluster={c} onLocate={locate} />
              ))}
            </ul>
          )}
        </aside>
      </div>
    </div>
  );
}
