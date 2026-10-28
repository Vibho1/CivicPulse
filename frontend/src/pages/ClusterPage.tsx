import { useEffect, useId, useMemo, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError, api, errorCode, errorMessage, mediaUrl, tooFar, type Cluster, type ClusterDetail, type Report, type Verification } from '../api';
import { useApp } from '../context/AppContext';
import { EscalationPanel, ResolvePanel, VerifyPanel, type ResolvePanelInput, type VerifyPanelInput } from '../components/ActionPanels';
import { Icon } from '../components/Icon';
import { CredibilityChip, ReportProvenance } from '../components/Provenance';
import { Timeline } from '../components/Timeline';
import { useToast } from '../components/Toast';
import { AgencyChip, AgencyCodeChip, Chip, ErrorState, LanguageBadge, ScoreBreakdownBars, ScoreRing, SeverityMeter, Skeleton, SlaBar, StatusBadge } from '../components/ui';
import { VerificationCard } from '../components/VerificationCard';
import { useI18n } from '../i18n';
import { copyText } from '../lib/csv';
import { exifFields } from '../lib/exif';
import { coordText, fmtConfidence, fmtDate, humanize, shortId } from '../lib/format';
import { proofPosition, tryGetPosition } from '../lib/geo';
import { agencyCode, canCorroborate, canResolve, canSetStatus, canVerify, verdictHeadline, verdictTone } from '../lib/status';
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
  const { t, fmt, label } = useI18n();
  const before = useMemo(() => {
    const urls: { url: string; caption: string }[] = [];
    const seen = new Set<string>();
    for (const r of reports) {
      const u = mediaUrl(r.photo_url);
      if (u && !seen.has(u)) {
        seen.add(u);
        urls.push({ url: u, caption: t('photos.beforeCaption', { reporter: shortId(r.reporter_id), time: fmt.timeAgo(r.created_at) }) });
      }
    }
    return urls;
  }, [reports, t, fmt]);
  const after = mediaUrl(cluster.after_photo_url);
  const proofs = verifications
    .filter((v) => v.kind === 'citizen')
    .map((v) => ({ url: mediaUrl(v.photo_url), caption: t('photos.proofCaption', { time: fmt.timeAgo(v.created_at) }), verdict: v.verdict }))
    .filter((p) => p.url);

  if (!before.length && !after && !proofs.length) return null;

  return (
    <section className="card" aria-labelledby="photos-title">
      <h2 id="photos-title">{t('photos.title')}</h2>
      {before.length > 0 && after ? (
        <div className="compare">
          <figure>
            <img src={before[0].url} alt={t('photos.beforeAlt')} />
            <figcaption>
              <span className="tag tag-before">{t('photos.before')}</span> {before[0].caption}
            </figcaption>
          </figure>
          <figure>
            <img src={after} alt={t('photos.afterAlt')} />
            <figcaption>
              <span className={`tag tag-after tone-${verdictTone(cluster.verification_verdict)}`}>{t('photos.after')}</span> {t('photos.official')} ·{' '}
              {cluster.resolved_at ? fmt.timeAgo(cluster.resolved_at) : ''}
              {cluster.verification_verdict ? ` · ${label('verdict', cluster.verification_verdict, humanize(cluster.verification_verdict.toLowerCase()))}` : ''}
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
            <img src={after} alt={t('photos.afterPhotoAlt')} loading="lazy" />
            <span>{t('photos.afterOfficial')}</span>
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
  const { t, tx, fmt, label } = useI18n();
  const photo = mediaUrl(r.photo_url);
  // `audio_url` is null unless the server makes voice notes public (PUBLIC_AUDIO); no player then.
  const audio = mediaUrl(r.audio_url);
  const transcript = r.transcript?.trim();
  const english = r.transcript_english?.trim();
  if (r.is_corroboration) {
    return (
      <li className="report-item corroboration">
        <Icon name="thumbs-up" size={16} />
        <div>
          {tx('cluster.report.corroboration', { reporter: <strong>{shortId(r.reporter_id)}</strong>, time: fmt.timeAgo(r.created_at) })}
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
        <CredibilityChip value={r.reporter_credibility} />
        <span className="muted small">
          {shortId(r.reporter_id)} · {fmt.timeAgo(r.created_at)} · {r.ai_mode.startsWith('gemini') ? 'Gemini' : humanize(r.ai_mode)}
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
            <p className="translation" lang="en">
              {transcript ? <span className="muted">{t('common.english')} </span> : null}
              {english}
            </p>
          ) : null}
          {audio ? <audio controls src={audio} preload="none" className="audio-player" /> : null}
          {r.hazards?.length ? (
            <div className="chips">
              {r.hazards.map((h) => (
                <span key={h} className="chip chip-warn">
                  {label('hazard', h, humanize(h))}
                </span>
              ))}
            </div>
          ) : null}
          <ReportProvenance report={r} />
        </div>
        {photo ? (
          <a href={photo} target="_blank" rel="noopener noreferrer" className="report-thumb">
            <img src={photo} alt={t('cluster.report.photoAlt')} loading="lazy" />
          </a>
        ) : null}
      </div>
    </li>
  );
}

/** Anyone can attach the official grievance (Sahaaya) complaint number so the two records can be cross-checked. */
function ExternalRefForm({ cluster, saving, disabled, onSave }: { cluster: Cluster; saving: boolean; disabled: boolean; onSave: (ref: string) => Promise<boolean> }) {
  const { t, fmt } = useI18n();
  const inputId = useId();
  const current = cluster.external_ref;
  const system = (cluster.external_system || 'sahaaya').toUpperCase();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const trimmed = value.trim();

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!trimmed || trimmed === current) return;
    if (await onSave(trimmed)) {
      setEditing(false);
      setValue('');
    }
  }

  if (current && !editing) {
    return (
      <div className="ext-ref ext-ref-set">
        <Icon name="file-text" size={15} />
        <span className="grow">
          {t('extref.ticket')}{' '}
          <strong>
            {system} #{current}
          </strong>
          {cluster.external_ref_at ? <span className="muted small"> · {t('extref.linked', { time: fmt.timeAgo(cluster.external_ref_at) })}</span> : null}
        </span>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => {
            setValue(current);
            setEditing(true);
          }}
          disabled={disabled}
        >
          {t('common.update')}
        </button>
      </div>
    );
  }

  return (
    <form className="ext-ref" onSubmit={(e) => void submit(e)}>
      <label htmlFor={inputId} className="field-label">
        {current ? t('extref.updateLabel', { system }) : t('extref.addLabel')}
      </label>
      <div className="row gap-s">
        <input id={inputId} className="input" value={value} onChange={(e) => setValue(e.target.value)} maxLength={64} placeholder={t('extref.placeholder')} autoComplete="off" disabled={saving} />
        <button type="submit" className="btn btn-secondary" disabled={disabled || !trimmed || trimmed === current}>
          {saving ? <span className="spinner" /> : null} {t('common.save')}
        </button>
        {current ? (
          <button type="button" className="btn btn-ghost" onClick={() => setEditing(false)} disabled={saving}>
            {t('common.cancel')}
          </button>
        ) : null}
      </div>
    </form>
  );
}

export default function ClusterPage() {
  const { id = '' } = useParams();
  const { officialMode, reporterId, dataVersion, bumpData, health, meta } = useApp();
  const toast = useToast();
  const { lang, t, tx, has, fmt, label } = useI18n();
  const q = useAsync<ClusterDetail>(() => api.cluster(id), [id, dataVersion]);

  const [panel, setPanel] = useState<Panel>('none');
  const [acting, setActing] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<Verification | null>(null);

  useEffect(() => {
    setPanel('none');
    setHighlight(null);
  }, [id]);

  /** The server words 409/422/429 warnings in English; other languages use the translated message for known codes. */
  function warnText(e: ApiError): string {
    if (lang === 'en') return e.message;
    const far = tooFar(e);
    if (far) {
      return far.distance_m !== null && far.max_distance_m !== null
        ? t('apiError.too_far', { distance: fmt.distance(far.distance_m), max: fmt.distance(far.max_distance_m) })
        : e.message;
    }
    const code = errorCode(e);
    return code && has(`apiError.${code}`) ? t(`apiError.${code}`) : e.message;
  }

  async function run<T>(key: string, fn: () => Promise<T>, after?: (res: T) => void) {
    setActing(key);
    try {
      const res = await fn();
      after?.(res);
    } catch (e) {
      // 409 = invalid transition, 429 = this citizen already backed it a few minutes ago,
      // 422 too_far = the device is too far from the issue to vouch for it.
      if (e instanceof ApiError && (e.status === 409 || e.status === 429 || tooFar(e) !== null)) toast.warn(warnText(e));
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
        <ErrorState message={notFound ? t('cluster.notFound', { id }) : (q.error ?? t('error.unknown'))} onRetry={q.reload} />
      </div>
    );
  }

  const { cluster: c, reports, verifications, events, previous_cluster } = q.data;
  const busy = acting !== null;
  const repeatWindowDays = meta?.repeat_failure_window_days ?? 180;
  const secondaryName = c.secondary_agency ? label('agencyName', c.secondary_agency, c.secondary_agency_label || c.secondary_agency_short || c.secondary_agency) : '';

  const corroborate = () =>
    run(
      'corroborate',
      async () => {
        const pos = await tryGetPosition(6000);
        // No fix, or only an IP/Wi-Fi guess (> 1 km): vouch from the issue's own spot instead.
        const fix = pos && pos.coords.accuracy <= 1000 ? pos.coords : null;
        return api.corroborate(c.id, {
          lat: fix ? fix.latitude : c.lat,
          lng: fix ? fix.longitude : c.lng,
          accuracy: fix ? fix.accuracy : undefined,
          reporter_id: reporterId,
        });
      },
      (res) => {
        toast.success(t('cluster.toast.corroborated', { reports: fmt.count('report', res.cluster.report_count) }));
        q.reload();
      },
    );

  const setStatus = (status: 'open' | 'in_progress') =>
    run(
      `status:${status}`,
      () => api.setStatus(c.id, { status, actor: 'official' }),
      (res) => {
        q.setData(res);
        toast.success(t('cluster.toast.status', { status: label('status', status, status.replace('_', ' ')) }));
      },
    );

  const resolve = (input: ResolvePanelInput) =>
    run(
      'resolve',
      async () => {
        // The photo's own EXIF GPS wins on the server; device position is the fallback (touch devices only).
        const device = input.after_photo ? await proofPosition() : null;
        return api.resolve(c.id, {
          after_photo: input.after_photo,
          note: input.note,
          actor: input.actor,
          ...exifFields(input.after_photo ? input.exif : null),
          lat: device?.lat,
          lng: device?.lng,
          accuracy: device?.accuracy,
        });
      },
      (res) => {
        q.setData(res);
        setHighlight(res.verification);
        setPanel('none');
        const verdict = res.verification.verdict;
        const tone = verdictTone(verdict);
        const headline = has(`verdictHeadline.${verdict}`) ? t(`verdictHeadline.${verdict}`) : verdictHeadline(verdict);
        if (tone === 'bad') toast.error(t('cluster.toast.unverified', { reason: headline.toLowerCase() || t('cluster.toast.proofFailed') }));
        else if (tone === 'good') toast.success(t('cluster.toast.closurePassed'));
        else toast.warn(t('cluster.toast.closureNoProof'));
        window.scrollTo({ top: 0, behavior: 'smooth' });
        // A closure sends proof requests to reporters: refresh the header inbox now rather than on its next poll.
        bumpData();
      },
    );

  const verify = (input: VerifyPanelInput) =>
    run(
      'verify',
      async () => {
        const device = await proofPosition();
        return api.verify(c.id, {
          photo: input.photo,
          note: input.note,
          reporter_id: reporterId,
          ...exifFields(input.exif),
          lat: device?.lat,
          lng: device?.lng,
          accuracy: device?.accuracy,
        });
      },
      (res) => {
        q.setData(res);
        setHighlight(res.verification);
        setPanel('none');
        const tone = verdictTone(res.verification.verdict);
        if (tone === 'good') toast.success(t('cluster.toast.verified'));
        else if (tone === 'bad') toast.error(t('cluster.toast.notFixed'));
        else toast.info(t('cluster.toast.inconclusive'));
        window.scrollTo({ top: 0, behavior: 'smooth' });
      },
    );

  const saveExternalRef = async (ref: string): Promise<boolean> => {
    let saved = false;
    await run(
      'external-ref',
      () => api.setExternalRef(c.id, { system: 'sahaaya', ref, actor: reporterId }),
      (res) => {
        q.setData(res);
        saved = true;
        toast.success(t('cluster.toast.extRef', { ref: res.cluster.external_ref ?? ref, id: c.id }));
      },
    );
    return saved;
  };

  async function copyId() {
    const ok = await copyText(c.id);
    if (ok) toast.success(t('cluster.toast.copied', { id: c.id }));
  }

  const togglePanel = (p: Panel) => setPanel((cur) => (cur === p ? 'none' : p));

  return (
    <div className="page detail">
      <nav className="crumbs" aria-label={t('nav.breadcrumb')}>
        <Link to="/">{t('nav.map')}</Link> <Icon name="chevron-right" size={12} /> <span>{c.id}</span>
      </nav>

      {highlight ? <VerificationCard verification={highlight} prominent onDismiss={() => setHighlight(null)} /> : null}

      <header className="card detail-header">
        <div className="detail-header-top">
          <div className="chips">
            <span className="chip chip-info">{label('category', c.category, c.category_label)}</span>
            <StatusBadge status={c.status} />
            {c.repeat_failure ? (
              <span className="chip chip-bad">
                <Icon name="flag" size={12} /> {t('common.repeatFailure')}
              </span>
            ) : null}
          </div>
          <button type="button" className="id-chip" onClick={() => void copyId()} title={t('cluster.copyId')}>
            {c.id} <Icon name="copy" size={13} />
          </button>
        </div>
        <h1>{c.title}</h1>
        <div className="detail-meta">
          <span>
            <Icon name="pin" size={14} /> {fmt.ward(c.ward)}
            {c.zone ? ` · ${t('common.zone', { zone: label('zone', c.zone, c.zone) })}` : ''}
            {c.landmark ? ` · ${c.landmark}` : ''}
          </span>
          <span>
            <Icon name="clock" size={14} /> {t('cluster.reportedUpdated', { created: fmt.timeAgo(c.created_at), updated: fmt.timeAgo(c.updated_at) })}
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
            <strong>{t('result.repeat.title')}</strong>{' '}
            {previous_cluster
              ? tx('cluster.repeat.bodyOn', {
                  date: fmtDate(previous_cluster.verified_at ?? previous_cluster.resolved_at, { time: false }),
                  link: <Link to={`/clusters/${previous_cluster.id}`}>{previous_cluster.id}</Link>,
                  days: repeatWindowDays,
                })
              : t('cluster.repeat.bodyRecent', { days: repeatWindowDays })}
          </div>
        </div>
      ) : null}

      <div className="detail-grid">
        <aside className="detail-side">
          <section className="card" aria-labelledby="impact-title">
            <h2 id="impact-title">{t('score.title')}</h2>
            <div className="impact-row">
              <ScoreRing score={c.impact_score} size={96} stroke={10} showLabel />
              <div className="impact-text">
                <div>
                  {c.reporter_count != null
                    ? tx('cluster.reportsFrom', {
                        reports: <strong>{fmt.count('report', c.report_count)}</strong>,
                        citizens: <strong>{fmt.count('citizen', c.reporter_count)}</strong>,
                      })
                    : <strong>{fmt.count('report', c.report_count)}</strong>}
                </div>
                <div>{tx('common.maxSeverity', { value: <strong>{c.max_severity}/5</strong> })}</div>
                {c.context.length ? <div className="muted small">{t('cluster.near', { places: c.context.map((x) => x.name).slice(0, 2).join(', ') })}</div> : null}
              </div>
            </div>
            <ScoreBreakdownBars cluster={c} />
            {c.hazards.length ? (
              <div className="chips">
                {c.hazards.map((h) => (
                  <span key={h} className="chip chip-warn">
                    {label('hazard', h, humanize(h))}
                  </span>
                ))}
              </div>
            ) : null}
          </section>

          <section className="card" aria-labelledby="sla-title">
            <h2 id="sla-title">{t('cluster.serviceLevel')}</h2>
            <SlaBar cluster={c} />
          </section>

          <section className="card routing" aria-labelledby="routing-title">
            <h2 id="routing-title">{t('routing.title')}</h2>
            <div className="routing-agency">
              {label('agencyName', c.agency, c.agency_label)} <AgencyCodeChip code={agencyCode(c.agency, c.agency_code)} />
            </div>
            {c.agency_reason ? <p className="routing-reason">{c.agency_reason}</p> : null}
            {c.routing_confidence != null ? (
              <div className="chips">
                <span className="chip chip-muted" title={t('routing.confidenceTitle')}>
                  {t('routing.confidence', { value: fmtConfidence(c.routing_confidence) })}
                </span>
              </div>
            ) : null}
            <dl className="kv">
              {c.external_ref ? (
                <>
                  <dt>{t('extref.ticket')}</dt>
                  <dd title={c.external_ref_at ? t('extref.linkedOn', { date: fmtDate(c.external_ref_at) }) : undefined}>
                    <strong>
                      {(c.external_system || 'sahaaya').toUpperCase()} #{c.external_ref}
                    </strong>
                  </dd>
                </>
              ) : null}
              <dt>{t('routing.helpline')}</dt>
              <dd>
                <a href={`tel:${c.agency_info.helpline.replace(/[^0-9+]/g, '')}`}>{c.agency_info.helpline}</a>
              </dd>
              <dt>{t('routing.onX')}</dt>
              <dd>
                <a href={`https://x.com/${c.agency_info.x_handle.replace('@', '')}`} target="_blank" rel="noopener noreferrer">
                  {c.agency_info.x_handle}
                </a>
              </dd>
              <dt>{t('routing.writeTo')}</dt>
              <dd>{label('agencyContact', c.agency, c.agency_info.email_hint)}</dd>
              <dt>{t('routing.scope')}</dt>
              <dd className="muted">{label('agencyScope', c.agency, c.agency_info.scope)}</dd>
            </dl>
            {c.secondary_agency ? (
              <div className="routing-secondary">
                <div className="routing-secondary-title">{t('routing.alsoResponsibleTitle')}</div>
                <div className="routing-secondary-agency">
                  {secondaryName} <AgencyCodeChip code={agencyCode(c.secondary_agency, c.secondary_agency_code)} />
                </div>
                {c.secondary_agency_reason ? <p className="muted small">{c.secondary_agency_reason}</p> : null}
                {c.secondary_agency_info?.helpline ? (
                  <dl className="kv">
                    <dt>{t('routing.helpline')}</dt>
                    <dd>
                      <a href={`tel:${c.secondary_agency_info.helpline.replace(/[^0-9+]/g, '')}`}>{c.secondary_agency_info.helpline}</a>
                    </dd>
                  </dl>
                ) : null}
              </div>
            ) : null}
          </section>

          <section className="card actions" aria-labelledby="actions-title">
            <h2 id="actions-title">{t('cluster.actions.title')}</h2>
            <div className="action-list">
              <button type="button" className="btn btn-secondary" onClick={() => void corroborate()} disabled={busy || !canCorroborate(c.status)} title={!canCorroborate(c.status) ? t('cluster.actions.corroborateDisabled') : undefined}>
                {acting === 'corroborate' ? <span className="spinner" /> : <Icon name="thumbs-up" size={16} />} {t('cluster.actions.corroborate')}
              </button>
              {canVerify(c.status) ? (
                <button type="button" className={`btn ${panel === 'verify' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => togglePanel('verify')} disabled={busy}>
                  <Icon name="camera" size={16} /> {t('verify.title')}
                </button>
              ) : null}
              <button type="button" className={`btn ${panel === 'escalate' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => togglePanel('escalate')} disabled={busy}>
                <Icon name="send" size={16} /> {t('escalate.action')}
              </button>
            </div>
            {c.status === 'resolved_verified' ? <p className="muted small">{t('cluster.verifiedNote')}</p> : null}

            <ExternalRefForm key={c.id} cluster={c} saving={acting === 'external-ref'} disabled={busy} onSave={saveExternalRef} />

            {officialMode ? (
              <div className="official-actions">
                <div className="official-label">
                  <Icon name="shield" size={14} /> {t('cluster.official.title')}
                </div>
                <div className="action-list">
                  {canSetStatus(c.status, 'in_progress') ? (
                    <button type="button" className="btn btn-secondary" onClick={() => void setStatus('in_progress')} disabled={busy}>
                      {acting === 'status:in_progress' ? <span className="spinner" /> : <Icon name="refresh" size={16} />} {t('cluster.official.inProgress')}
                    </button>
                  ) : null}
                  {canSetStatus(c.status, 'open') ? (
                    <button type="button" className="btn btn-ghost" onClick={() => void setStatus('open')} disabled={busy}>
                      {acting === 'status:open' ? <span className="spinner" /> : <Icon name="rotate" size={16} />} {t('cluster.official.reopen')}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className={`btn ${panel === 'resolve' ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => togglePanel('resolve')}
                    disabled={busy || !canResolve(c.status)}
                    title={!canResolve(c.status) ? t('cluster.official.cannotResolve', { status: label('status', c.status, c.status_label) }) : undefined}
                  >
                    <Icon name="check-circle" size={16} /> {t('resolve.title')}
                  </button>
                </div>
                {!canResolve(c.status) ? <p className="muted small">{t('cluster.official.alreadyClosed')}</p> : null}
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
              {t('cluster.closureProof')} <span className="count">{verifications.length}</span>
            </h2>
            {verifications.length === 0 ? (
              <p className="muted">
                {t('cluster.noClosure')} {c.status === 'open' || c.status === 'in_progress' ? t('cluster.noClosureHint') : ''}
              </p>
            ) : (
              <div className="stack">
                {[...verifications].reverse().map((v) => (
                  <VerificationCard key={v.id} verification={v} />
                ))}
              </div>
            )}
            {c.resolution_note && !verifications.length ? <p className="muted small">{t('cluster.resolutionNote', { note: c.resolution_note })}</p> : null}
          </section>

          <section className="card" aria-labelledby="reports-title">
            <h2 id="reports-title">
              {t('cluster.reports')} <span className="count">{reports.length}</span>
            </h2>
            {health?.features && !health.features.public_audio && reports.some((r) => !r.is_corroboration && !r.audio_url && !r.text && !!r.transcript?.trim()) ? (
              <p className="muted small">{t('cluster.audioPrivate')}</p>
            ) : null}
            {reports.length === 0 ? (
              <p className="muted">{t('cluster.noReports')}</p>
            ) : (
              <ul className="report-list">
                {[...reports].sort((a, b) => a.created_at.localeCompare(b.created_at)).map((r) => (
                  <ReportItem key={r.id} r={r} />
                ))}
              </ul>
            )}
          </section>

          <section className="card" aria-labelledby="timeline-title">
            <h2 id="timeline-title">{t('cluster.timeline')}</h2>
            <Timeline events={events} />
          </section>

          <section className="card detail-foot">
            <div className="chips">
              <AgencyChip agency={c.agency} short={c.agency_short} label={c.agency_label} reason={c.agency_reason} />
              <Chip tone="muted">{t('cluster.created', { date: fmtDate(c.created_at) })}</Chip>
              {c.resolved_at ? <Chip tone="muted">{t('cluster.resolved', { date: fmtDate(c.resolved_at) })}</Chip> : null}
              {c.verified_at ? <Chip tone="ok">{t('cluster.verified', { date: fmtDate(c.verified_at) })}</Chip> : null}
              {c.closure_count > 1 ? <Chip tone="warn">{t('cluster.closedTimes', { count: c.closure_count })}</Chip> : null}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
