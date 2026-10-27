import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError, api, errorMessage, mediaUrl, type Cluster, type ClusterDetail, type FormFile, type Report, type Verification } from '../api';
import { useApp } from '../context/AppContext';
import { EscalationPanel, ResolvePanel, VerifyPanel } from '../components/ActionPanels';
import { Icon } from '../components/Icon';
import { Timeline } from '../components/Timeline';
import { useToast } from '../components/Toast';
import { AgencyChip, Chip, ErrorState, LanguageBadge, ScoreBreakdownBars, ScoreRing, SeverityMeter, Skeleton, SlaBar, StatusBadge } from '../components/ui';
import { VerificationCard } from '../components/VerificationCard';
import { copyText } from '../lib/csv';
import { coordText, fmtDate, humanize, plural, shortId, timeAgo } from '../lib/format';
import { getPosition } from '../lib/geo';
import { canCorroborate, canResolve, canSetStatus, canVerify, verdictTone } from '../lib/status';
import { useAsync } from '../lib/useAsync';

type Panel = 'none' | 'verify' | 'escalate' | 'resolve';

function DetailSkeleton() {
  return (
    <div className="page detail">
      <div className="card detail-header">
        <Skeleton h={14} w={120} />
        <Skeleton h={28} w="70%" />
        <Skeleton h={20} w="50%" />
      </div>
      <div className="detail-grid">
        <div className="detail-side">
          <div className="card">
            <Skeleton h={96} w={96} r={48} />
            <Skeleton h={14} />
            <Skeleton h={14} />
          </div>
        </div>
        <div className="detail-main">
          <div className="card">
            <Skeleton h={180} />
          </div>
        </div>
      </div>
    </div>
  );
}

function PhotoStrip({ cluster, reports, verifications }: { cluster: Cluster; reports: Report[]; verifications: Verification[] }) {
  const before = useMemo(() => {
    const urls: { url: string; caption: string }[] = [];
    const seen = new Set<string>();
    for (const r of reports) {
      const u = mediaUrl(r.photo_url);
      if (u && !seen.has(u)) {
        seen.add(u);
        urls.push({ url: u, caption: `Before · ${shortId(r.reporter_id)} · ${timeAgo(r.created_at)}` });
      }
    }
    return urls;
  }, [reports]);
  const after = mediaUrl(cluster.after_photo_url);
  const proofs = verifications.filter((v) => v.kind === 'citizen').map((v) => ({ url: mediaUrl(v.photo_url), caption: `Citizen proof · ${timeAgo(v.created_at)}`, verdict: v.verdict })).filter((p) => p.url);

  if (!before.length && !after && !proofs.length) return null;

  return (
    <section className="card" aria-labelledby="photos-title">
      <h2 id="photos-title">Photos</h2>
      {before.length > 0 && after ? (
        <div className="compare">
          <figure>
            <img src={before[0].url} alt="Before: citizen report photo" />
            <figcaption>
              <span className="tag tag-before">Before</span> {before[0].caption}
            </figcaption>
          </figure>
          <figure>
            <img src={after} alt="After: official closure photo" />
            <figcaption>
              <span className={`tag tag-after tone-${verdictTone(cluster.verification_verdict)}`}>After</span> official · {cluster.resolved_at ? timeAgo(cluster.resolved_at) : ''}
              {cluster.verification_verdict ? ` · ${humanize(cluster.verification_verdict.toLowerCase())}` : ''}
            </figcaption>
          </figure>
        </div>
      ) : null}
      <div className="thumbs">
        {(before.length > 0 && after ? before.slice(1) : before).map((p) => (
          <a key={p.url} href={p.url} target="_blank" rel="noopener noreferrer" className="thumb">
            <img src={p.url} alt={p.caption} loading="lazy" />
            <span>{p.caption}</span>
          </a>
        ))}
        {after && !before.length ? (
          <a href={after} target="_blank" rel="noopener noreferrer" className="thumb">
            <img src={after} alt="After photo" loading="lazy" />
            <span>After · official</span>
          </a>
        ) : null}
        {proofs.map((p) => (
          <a key={p.url!} href={p.url!} target="_blank" rel="noopener noreferrer" className={`thumb thumb-${verdictTone(p.verdict)}`}>
            <img src={p.url!} alt={p.caption} loading="lazy" />
            <span>{p.caption}</span>
          </a>
        ))}
      </div>
    </section>
  );
}

function ReportItem({ r }: { r: Report }) {
  const photo = mediaUrl(r.photo_url);
  const audio = mediaUrl(r.audio_url);
  const transcript = r.transcript?.trim();
  const english = r.transcript_english?.trim();
  if (r.is_corroboration) {
    return (
      <li className="report-item corroboration">
        <Icon name="thumbs-up" size={16} />
        <div>
          <strong>{shortId(r.reporter_id)}</strong> confirmed this is still there · {timeAgo(r.created_at)}
          {r.text ? <div className="muted small">“{r.text}”</div> : null}
        </div>
      </li>
    );
  }
  return (
    <li className="report-item">
      <div className="report-head">
        <LanguageBadge code={r.language} />
        <SeverityMeter severity={r.severity} compact />
        <span className="muted small">
          {shortId(r.reporter_id)} · {timeAgo(r.created_at)} · {r.ai_mode.startsWith('gemini') ? 'Gemini' : humanize(r.ai_mode)}
        </span>
      </div>
      <div className="report-body">
        <div className="report-text">
          {transcript ? (
            <blockquote className="transcript" lang={r.language?.split('-')[0] || undefined}>
              “{transcript}”
            </blockquote>
          ) : null}
          {english && english !== transcript ? (
            <p className="translation">
              {transcript ? <span className="muted">English: </span> : null}
              {english}
            </p>
          ) : null}
          {audio ? <audio controls src={audio} preload="none" className="audio-player" /> : null}
          {r.hazards?.length ? (
            <div className="chips">
              {r.hazards.map((h) => (
                <span key={h} className="chip chip-warn">
                  {humanize(h)}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        {photo ? (
          <a href={photo} target="_blank" rel="noopener noreferrer" className="report-thumb">
            <img src={photo} alt="Report photo" loading="lazy" />
          </a>
        ) : null}
      </div>
    </li>
  );
}

export default function ClusterPage() {
  const { id = '' } = useParams();
  const { officialMode, reporterId, dataVersion } = useApp();
  const toast = useToast();
  const q = useAsync<ClusterDetail>(() => api.cluster(id), [id, dataVersion]);

  const [panel, setPanel] = useState<Panel>('none');
  const [acting, setActing] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<Verification | null>(null);

  useEffect(() => {
    setPanel('none');
    setHighlight(null);
  }, [id]);

  async function run<T>(key: string, fn: () => Promise<T>, after?: (res: T) => void) {
    setActing(key);
    try {
      const res = await fn();
      after?.(res);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) toast.warn(e.message);
      else toast.error(errorMessage(e));
    } finally {
      setActing(null);
    }
  }

  if (q.loading && !q.data) return <DetailSkeleton />;
  if (!q.data) {
    const notFound = q.error?.toLowerCase().includes('not found');
    return (
      <div className="page detail">
        <ErrorState message={notFound ? `Issue ${id} was not found. It may have been wiped by a reset.` : (q.error ?? 'Unknown error')} onRetry={q.reload} />
      </div>
    );
  }

  const { cluster: c, reports, verifications, events, previous_cluster } = q.data;
  const busy = acting !== null;

  const corroborate = () =>
    run(
      'corroborate',
      async () => {
        const pos = await getPosition(6000).catch(() => null);
        return api.corroborate(c.id, { lat: pos?.coords.latitude ?? c.lat, lng: pos?.coords.longitude ?? c.lng, reporter_id: reporterId });
      },
      (res) => {
        toast.success(`Thanks — ${plural(res.cluster.report_count, 'report')} now back this issue.`);
        q.reload();
      },
    );

  const setStatus = (status: 'open' | 'in_progress') =>
    run(
      `status:${status}`,
      () => api.setStatus(c.id, { status, actor: 'official' }),
      (res) => {
        q.setData(res);
        toast.success(`Status set to ${status.replace('_', ' ')}.`);
      },
    );

  const resolve = (input: { after_photo?: FormFile; note?: string; actor?: string }) =>
    run(
      'resolve',
      () => api.resolve(c.id, input),
      (res) => {
        q.setData(res);
        setHighlight(res.verification);
        setPanel('none');
        const tone = verdictTone(res.verification.verdict);
        if (tone === 'bad') toast.error(`Closure disputed: ${res.verification.verdict.replace(/_/g, ' ').toLowerCase()}.`);
        else if (tone === 'good') toast.success('Closure check passed — awaiting citizen confirmation.');
        else toast.warn('Closure recorded without proof — citizens have been asked to verify.');
        window.scrollTo({ top: 0, behavior: 'smooth' });
      },
    );

  const verify = (input: { photo: FormFile; note?: string }) =>
    run(
      'verify',
      () => api.verify(c.id, { ...input, reporter_id: reporterId }),
      (res) => {
        q.setData(res);
        setHighlight(res.verification);
        setPanel('none');
        const tone = verdictTone(res.verification.verdict);
        if (tone === 'good') toast.success('Fix verified. Thank you for closing the loop!');
        else if (tone === 'bad') toast.error('Not fixed — closure disputed and sent back to the agency.');
        else toast.info('Inconclusive — thanks, another angle may help.');
        window.scrollTo({ top: 0, behavior: 'smooth' });
      },
    );

  async function copyId() {
    const ok = await copyText(c.id);
    if (ok) toast.success(`${c.id} copied`);
  }

  const togglePanel = (p: Panel) => setPanel((cur) => (cur === p ? 'none' : p));

  return (
    <div className="page detail">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/">Map</Link> <Icon name="chevron-right" size={12} /> <span>{c.id}</span>
      </nav>

      {highlight ? <VerificationCard verification={highlight} prominent onDismiss={() => setHighlight(null)} /> : null}

      <header className="card detail-header">
        <div className="detail-header-top">
          <div className="chips">
            <span className="chip chip-info">{c.category_label}</span>
            <StatusBadge status={c.status} />
            {c.repeat_failure ? (
              <span className="chip chip-bad">
                <Icon name="flag" size={12} /> Repeat failure
              </span>
            ) : null}
          </div>
          <button type="button" className="id-chip" onClick={() => void copyId()} title="Copy issue id">
            {c.id} <Icon name="copy" size={13} />
          </button>
        </div>
        <h1>{c.title}</h1>
        <div className="detail-meta">
          <span>
            <Icon name="pin" size={14} /> {c.ward}
            {c.zone ? ` · ${c.zone} zone` : ''}
            {c.landmark ? ` · ${c.landmark}` : ''}
          </span>
          <span>
            <Icon name="clock" size={14} /> Reported {timeAgo(c.created_at)} · updated {timeAgo(c.updated_at)}
          </span>
          <a className="muted" href={`https://www.openstreetmap.org/?mlat=${c.lat}&mlon=${c.lng}#map=18/${c.lat}/${c.lng}`} target="_blank" rel="noopener noreferrer">
            {coordText(c.lat, c.lng)} <Icon name="external" size={12} />
          </a>
        </div>
        {c.description ? <p className="detail-desc">{c.description}</p> : null}
      </header>

      {c.repeat_failure ? (
        <div className="banner banner-bad">
          <Icon name="flag" size={20} />
          <div>
            <strong>Repeat failure.</strong> This spot was{' '}
            {previous_cluster ? (
              <>
                marked fixed on {fmtDate(previous_cluster.verified_at ?? previous_cluster.resolved_at, { time: false })} (<Link to={`/clusters/${previous_cluster.id}`}>{previous_cluster.id}</Link>)
              </>
            ) : (
              'verified as fixed recently'
            )}{' '}
            and failed again within 180 days — a possible warranty / defect-liability claim against the contractor.
          </div>
        </div>
      ) : null}

      <div className="detail-grid">
        <aside className="detail-side">
          <section className="card" aria-labelledby="impact-title">
            <h2 id="impact-title">Impact score</h2>
            <div className="impact-row">
              <ScoreRing score={c.impact_score} size={96} stroke={10} showLabel />
              <div className="impact-text">
                <div>
                  <strong>{plural(c.report_count, 'report')}</strong>
                </div>
                <div>
                  Max severity <strong>{c.max_severity}/5</strong>
                </div>
                {c.context.length ? <div className="muted small">Near {c.context.map((x) => x.name).slice(0, 2).join(', ')}</div> : null}
              </div>
            </div>
            <ScoreBreakdownBars cluster={c} />
            {c.hazards.length ? (
              <div className="chips">
                {c.hazards.map((h) => (
                  <span key={h} className="chip chip-warn">
                    {humanize(h)}
                  </span>
                ))}
              </div>
            ) : null}
          </section>

          <section className="card" aria-labelledby="sla-title">
            <h2 id="sla-title">Service level</h2>
            <SlaBar cluster={c} />
          </section>

          <section className="card routing" aria-labelledby="routing-title">
            <h2 id="routing-title">Routed to</h2>
            <div className="routing-agency">{c.agency_label}</div>
            {c.agency_reason ? <p className="routing-reason">{c.agency_reason}</p> : null}
            <dl className="kv">
              <dt>Helpline</dt>
              <dd>
                <a href={`tel:${c.agency_info.helpline.replace(/[^0-9+]/g, '')}`}>{c.agency_info.helpline}</a>
              </dd>
              <dt>On X</dt>
              <dd>
                <a href={`https://x.com/${c.agency_info.x_handle.replace('@', '')}`} target="_blank" rel="noopener noreferrer">
                  {c.agency_info.x_handle}
                </a>
              </dd>
              <dt>Write to</dt>
              <dd>{c.agency_info.email_hint}</dd>
              <dt>Scope</dt>
              <dd className="muted">{c.agency_info.scope}</dd>
            </dl>
          </section>

          <section className="card actions" aria-labelledby="actions-title">
            <h2 id="actions-title">Act on this</h2>
            <div className="action-list">
              <button type="button" className="btn btn-secondary" onClick={() => void corroborate()} disabled={busy || !canCorroborate(c.status)} title={!canCorroborate(c.status) ? 'Verified as fixed — file a fresh report if it is back' : undefined}>
                {acting === 'corroborate' ? <span className="spinner" /> : <Icon name="thumbs-up" size={16} />} I see this too
              </button>
              {canVerify(c.status) ? (
                <button type="button" className={`btn ${panel === 'verify' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => togglePanel('verify')} disabled={busy}>
                  <Icon name="camera" size={16} /> Submit proof photo
                </button>
              ) : null}
              <button type="button" className={`btn ${panel === 'escalate' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => togglePanel('escalate')} disabled={busy}>
                <Icon name="send" size={16} /> Draft escalation
              </button>
            </div>
            {c.status === 'resolved_verified' ? <p className="muted small">This issue is verified as fixed. If it has reappeared, file a new report — it will be flagged as a repeat failure.</p> : null}

            {officialMode ? (
              <div className="official-actions">
                <div className="official-label">
                  <Icon name="shield" size={14} /> Official actions
                </div>
                <div className="action-list">
                  {canSetStatus(c.status, 'in_progress') ? (
                    <button type="button" className="btn btn-secondary" onClick={() => void setStatus('in_progress')} disabled={busy}>
                      {acting === 'status:in_progress' ? <span className="spinner" /> : <Icon name="refresh" size={16} />} Mark in progress
                    </button>
                  ) : null}
                  {canSetStatus(c.status, 'open') ? (
                    <button type="button" className="btn btn-ghost" onClick={() => void setStatus('open')} disabled={busy}>
                      {acting === 'status:open' ? <span className="spinner" /> : <Icon name="rotate" size={16} />} Back to open
                    </button>
                  ) : null}
                  <button type="button" className={`btn ${panel === 'resolve' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => togglePanel('resolve')} disabled={busy || !canResolve(c.status)} title={!canResolve(c.status) ? `Cannot resolve an issue in status “${c.status_label}”` : undefined}>
                    <Icon name="check-circle" size={16} /> Mark resolved
                  </button>
                </div>
                {!canResolve(c.status) ? <p className="muted small">Already closed. A citizen proof photo decides whether it becomes verified or disputed.</p> : null}
              </div>
            ) : null}
          </section>

          {panel === 'verify' ? <VerifyPanel busy={acting === 'verify'} onSubmit={verify} onClose={() => setPanel('none')} /> : null}
          {panel === 'resolve' && officialMode ? <ResolvePanel busy={acting === 'resolve'} onSubmit={resolve} onClose={() => setPanel('none')} /> : null}
          {panel === 'escalate' ? <EscalationPanel cluster={c} onClose={() => setPanel('none')} /> : null}
        </aside>

        <div className="detail-main">
          <PhotoStrip cluster={c} reports={reports} verifications={verifications} />

          <section className="card" aria-labelledby="verif-title">
            <h2 id="verif-title">
              Closure proof <span className="count">{verifications.length}</span>
            </h2>
            {verifications.length === 0 ? (
              <p className="muted">
                No closure has been attempted yet.{' '}
                {c.status === 'open' || c.status === 'in_progress' ? 'When an official marks this resolved, the after-photo will be AI-checked against the citizen photos here.' : ''}
              </p>
            ) : (
              <div className="stack">
                {[...verifications].reverse().map((v) => (
                  <VerificationCard key={v.id} verification={v} />
                ))}
              </div>
            )}
            {c.resolution_note && !verifications.length ? <p className="muted small">Resolution note: {c.resolution_note}</p> : null}
          </section>

          <section className="card" aria-labelledby="reports-title">
            <h2 id="reports-title">
              Reports <span className="count">{reports.length}</span>
            </h2>
            {reports.length === 0 ? (
              <p className="muted">No reports.</p>
            ) : (
              <ul className="report-list">
                {[...reports].sort((a, b) => a.created_at.localeCompare(b.created_at)).map((r) => (
                  <ReportItem key={r.id} r={r} />
                ))}
              </ul>
            )}
          </section>

          <section className="card" aria-labelledby="timeline-title">
            <h2 id="timeline-title">Timeline</h2>
            <Timeline events={events} />
          </section>

          <section className="card detail-foot">
            <div className="chips">
              <AgencyChip short={c.agency_short} label={c.agency_label} reason={c.agency_reason} />
              <Chip tone="muted">Created {fmtDate(c.created_at)}</Chip>
              {c.resolved_at ? <Chip tone="muted">Resolved {fmtDate(c.resolved_at)}</Chip> : null}
              {c.verified_at ? <Chip tone="ok">Verified {fmtDate(c.verified_at)}</Chip> : null}
              {c.closure_count > 1 ? <Chip tone="warn">Closed {c.closure_count} times</Chip> : null}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
