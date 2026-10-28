import { Link } from 'react-router-dom';
import { mediaUrl, type DuplicateSubmission, type EmergencyNotice, type Extraction, type ReportResponse } from '../api';
import { useApp } from '../context/AppContext';
import { useI18n } from '../i18n';
import { coordText, fmtConfidence, fmtDate, humanize } from '../lib/format';
import { agencyCode } from '../lib/status';
import { Icon } from './Icon';
import { CredibilityChip, PhotoFlagChips } from './Provenance';
import { AgencyChip, AgencyCodeChip, LanguageBadge, ScoreBreakdownBars, ScoreRing, SeverityMeter, StatusBadge } from './ui';

interface Props {
  result: ReportResponse;
  onReset: () => void;
}

/** CivicPulse does not dispatch emergency services: point the reporter at 112 first. */
function EmergencyBanner({ emergency }: { emergency: EmergencyNotice }) {
  const { lang, t } = useI18n();
  const number = emergency.number || '112';
  // The server's message is English; other languages use the translated notice.
  const message = lang === 'en' && emergency.message ? emergency.message : t('emergency.body', { number });
  return (
    <div className="banner banner-bad emergency" role="alert">
      <Icon name="alert" size={22} />
      <div className="grow">
        <strong>{message}</strong>
      </div>
      <a className="btn btn-danger" href={`tel:${number}`}>
        <Icon name="phone" size={16} /> {t('emergency.call', { number })}
      </a>
    </div>
  );
}

function Banner({ result }: { result: ReportResponse }) {
  const { meta } = useApp();
  const { t, fmt, label } = useI18n();
  const { cluster, merged, reopened, repeat_failure, previous_cluster } = result;
  if (repeat_failure) {
    const when = previous_cluster?.verified_at ?? previous_cluster?.resolved_at ?? null;
    const days = meta?.repeat_failure_window_days ?? 180;
    return (
      <div className="banner banner-bad" role="status">
        <Icon name="flag" size={20} />
        <div>
          <strong>{t('result.repeat.title')}</strong>{' '}
          {when ? t('result.repeat.bodyOn', { date: fmtDate(when, { time: false }), days }) : t('result.repeat.bodyRecent', { days })}
          {previous_cluster ? (
            <>
              {' '}
              <Link to={`/clusters/${previous_cluster.id}`}>{t('result.repeat.previous', { id: previous_cluster.id })}</Link>
            </>
          ) : null}
        </div>
      </div>
    );
  }
  if (reopened) {
    return (
      <div className="banner banner-bad" role="status">
        <Icon name="rotate" size={20} />
        <div>
          <strong>{t('result.reopened.title')}</strong> {t('result.reopened.body', { id: cluster.id })}
        </div>
      </div>
    );
  }
  if (merged) {
    return (
      <div className="banner banner-info" role="status">
        <Icon name="merge" size={20} />
        <div>
          <strong>{t('result.merged.title', { id: cluster.id })}</strong> {t('result.merged.body', { reports: fmt.count('report', cluster.report_count) })}
        </div>
      </div>
    );
  }
  return (
    <div className="banner banner-good" role="status">
      <Icon name="check-circle" size={20} />
      <div>
        <strong>{t('result.created.title', { id: cluster.id })}</strong> {t('result.created.body', { agency: label('agency', cluster.agency, cluster.agency_short) })}
      </div>
    </div>
  );
}

export function ReportResult({ result, onReset }: Props) {
  const { t, tx, fmt, label } = useI18n();
  const { report, cluster, extraction, ai_mode, location_warning, emergency } = result;
  const transcript = report.transcript?.trim();
  const english = report.transcript_english?.trim();
  const hazards = report.hazards?.length ? report.hazards : cluster.hazards;
  const ev = report.evidence ?? {};
  const photo = mediaUrl(report.photo_url);
  // The reporter's own recording: only returned in this POST response (or when audio is public).
  const audio = mediaUrl(report.audio_url);
  const gemini = ai_mode.startsWith('gemini');
  const dims = fmt.dimensions(report.parsed?.estimated_dimensions_cm);
  const flags = report.photo_flags ?? [];
  const blurred = flags.includes('faces_or_plates_blurred') || (report.privacy_blurred ?? 0) > 0;
  const secondaryName = cluster.secondary_agency
    ? label('agencyName', cluster.secondary_agency, cluster.secondary_agency_label || cluster.secondary_agency_short || cluster.secondary_agency)
    : '';

  return (
    <section className="result card" aria-label={t('result.aria')}>
      {emergency && emergency.is_emergency !== false ? <EmergencyBanner emergency={emergency} /> : null}
      <Banner result={result} />
      {location_warning ? (
        <div className="banner banner-warn" role="note">
          <Icon name="alert" size={18} />
          <div>{location_warning}</div>
        </div>
      ) : null}

      <header className="result-head">
        <div>
          <div className="eyebrow">{t('result.eyebrow', { id: report.id })}</div>
          <h2>{report.title || cluster.title}</h2>
          <div className="chips">
            <span className="chip chip-info">{label('category', report.category, report.category_label)}</span>
            <LanguageBadge code={report.language} />
            <StatusBadge status={cluster.status} size="sm" />
            {report.landmark ? (
              <span className="chip chip-muted">
                <Icon name="pin" size={12} /> {report.landmark}
              </span>
            ) : null}
            <CredibilityChip value={report.reporter_credibility} />
          </div>
        </div>
        {photo ? <img className="result-photo" src={photo} alt={t('result.photoAlt')} /> : null}
      </header>

      <div className="result-grid">
        <div className="result-col">
          {(transcript || english || audio) && (
            <div className="block">
              <div className="block-title">
                <Icon name="mic" size={15} /> {t('result.whatYouSaid')}
              </div>
              {transcript ? (
                <blockquote className="transcript" lang={report.language?.split('-')[0] || undefined}>
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
              {report.description && report.description !== english ? <p className="muted small">{t('result.engineerSummary', { text: report.description })}</p> : null}
            </div>
          )}

          <div className="block">
            <div className="block-title">
              <Icon name="alert" size={15} /> {t('common.severity')}
            </div>
            <SeverityMeter severity={report.severity} />
            {dims ? (
              <p className="muted small">{t('dims.estimated', { value: dims })}</p>
            ) : report.size_estimate ? (
              <p className="muted small">{t('result.size', { size: report.size_estimate })}</p>
            ) : null}
          </div>

          <div className="routing routing-hero">
            <div className="routing-head">
              <Icon name="send" size={18} />
              <span>{t('routing.title')}</span>
            </div>
            <div className="routing-agency">
              {label('agencyName', cluster.agency, cluster.agency_label)} <AgencyCodeChip code={agencyCode(cluster.agency, cluster.agency_code)} />
            </div>
            <p className="routing-reason">{report.agency_reason || cluster.agency_reason || extraction.agency_reasoning || t('result.defaultRouting')}</p>
            <div className="chips">
              <AgencyChip agency={cluster.agency} short={cluster.agency_short} label={cluster.agency_label} />
              {cluster.routing_confidence != null ? (
                <span className="chip chip-muted" title={t('routing.confidenceTitle')}>
                  {t('routing.confidence', { value: fmtConfidence(cluster.routing_confidence) })}
                </span>
              ) : null}
              <span className="chip chip-muted">{t('routing.helplineChip', { number: cluster.agency_info.helpline })}</span>
              <span className="chip chip-muted">{cluster.agency_info.x_handle}</span>
            </div>
            {cluster.secondary_agency ? (
              <div className="routing-secondary">
                <div>{tx('routing.alsoResponsible', { agency: <strong>{secondaryName}</strong> })}</div>
                {cluster.secondary_agency_reason ? <p className="muted small">{cluster.secondary_agency_reason}</p> : null}
                <div className="chips">
                  <AgencyChip
                    agency={cluster.secondary_agency}
                    short={cluster.secondary_agency_short || cluster.secondary_agency}
                    label={cluster.secondary_agency_label ?? undefined}
                    reason={cluster.secondary_agency_reason}
                  />
                  <AgencyCodeChip code={agencyCode(cluster.secondary_agency, cluster.secondary_agency_code)} />
                  {cluster.secondary_agency_info?.helpline ? (
                    <span className="chip chip-muted">{t('routing.helplineChip', { number: cluster.secondary_agency_info.helpline })}</span>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>

          {(hazards.length > 0 || ev.recent_digging || (ev.utility_work_type && ev.utility_work_type !== 'none')) && (
            <div className="block">
              <div className="block-title">
                <Icon name="zap" size={15} /> {t('result.hazardsEvidence')}
              </div>
              <div className="chips">
                {hazards.map((h) => (
                  <span key={h} className="chip chip-warn">
                    {label('hazard', h, humanize(h))}
                  </span>
                ))}
                {ev.recent_digging ? (
                  <span className="chip chip-bad">
                    <Icon name="alert" size={12} /> {t('evidence.recentDigging')}
                  </span>
                ) : null}
                {ev.utility_work_type && ev.utility_work_type !== 'none' ? (
                  <span className="chip chip-bad">{t('evidence.utilityWork', { type: label('utility', ev.utility_work_type, humanize(ev.utility_work_type)) })}</span>
                ) : null}
              </div>
            </div>
          )}

          {ev.photo_provided || flags.length > 0 ? (
            <div className="block">
              <div className="block-title">
                <Icon name="image" size={15} /> {t('result.photoCheck')}
              </div>
              <div className="chips">
                {ev.photo_provided ? (
                  <>
                    <span className={`chip ${ev.photo_usable ? 'chip-ok' : 'chip-warn'}`}>{ev.photo_usable ? t('evidence.photoUsable') : t('evidence.photoUnclear')}</span>
                    <span className={`chip ${ev.photo_matches_description === false ? 'chip-warn' : 'chip-ok'}`}>
                      {ev.photo_matches_description === false ? t('evidence.noMatch') : t('evidence.matches')}
                    </span>
                  </>
                ) : null}
                {ev.people_or_plates_visible && !blurred ? (
                  <span className="chip chip-warn" title={t('evidence.facesTitle')}>
                    {t('evidence.facesVisible')}
                  </span>
                ) : null}
                <PhotoFlagChips flags={flags} blurred={report.privacy_blurred ?? 0} />
              </div>
            </div>
          ) : null}
        </div>

        <div className="result-col">
          <div className="block impact-block">
            <div className="block-title">
              <Icon name="activity" size={15} /> {t('score.title')}
            </div>
            <div className="impact-row">
              <ScoreRing score={cluster.impact_score} size={88} stroke={9} showLabel />
              <div className="impact-text">
                <div>
                  <strong>{fmt.count('report', cluster.report_count)}</strong>
                  {cluster.reporter_count != null ? (
                    <>
                      {' '}
                      · <strong>{fmt.count('citizen', cluster.reporter_count)}</strong>
                    </>
                  ) : null}{' '}
                  · {tx('common.maxSeverityLower', { value: <strong>{cluster.max_severity}/5</strong> })}
                </div>
                <div className="muted small">
                  {fmt.ward(cluster.ward)}
                  {cluster.zone ? ` · ${label('zone', cluster.zone, cluster.zone)}` : ''} · {coordText(cluster.lat, cluster.lng)}
                </div>
                <div className="muted small">{t('sla.targetLong', { hours: cluster.sla_hours })}</div>
              </div>
            </div>
            <ScoreBreakdownBars cluster={cluster} />
          </div>

          <p className="ai-note">
            <Icon name={gemini ? 'spark' : 'info'} size={14} />
            {gemini
              ? tx('result.parsedGemini', { engine: <strong>Gemini</strong>, value: `${Math.round((report.confidence ?? 0) * 100)}%` })
              : tx('result.parsedOffline', { mode: <strong>{t('result.offlineMode')}</strong>, key: <code>GEMINI_API_KEY</code> })}
          </p>
        </div>
      </div>

      <footer className="result-actions">
        <Link to={`/clusters/${cluster.id}`} className="btn btn-primary btn-lg">
          {t('result.openIssue', { id: cluster.id })} <Icon name="chevron-right" size={16} />
        </Link>
        <button type="button" className="btn btn-ghost" onClick={onReset}>
          <Icon name="plus-circle" size={16} /> {t('result.another')}
        </button>
      </footer>
    </section>
  );
}

/** Friendly card for the 422 "not a civic issue / low confidence" response. */
export function RejectedCard({ message, extraction, onDismiss, code = null }: { message: string; extraction: Extraction | null; onDismiss: () => void; code?: string | null }) {
  const { lang, t, has, fmt } = useI18n();
  const heard = extraction?.transcript?.trim() || extraction?.transcript_english?.trim() || '';
  // English keeps the server's wording; other languages use the translated message for known codes.
  const title = lang !== 'en' && code && has(`apiError.${code}`) ? t(`apiError.${code}`) : message;
  return (
    <div className="banner banner-warn rejected" role="alert">
      <Icon name="info" size={20} />
      <div>
        <strong>{title}</strong>
        <p className="small">{code === 'low_confidence' ? t('rejected.lowConfidence') : t('rejected.body')}</p>
        {heard ? (
          <p className="small muted">
            {t('rejected.heard', { text: heard })}
            {extraction?.language ? ` · ${fmt.language(extraction.language)}` : ''}
            {typeof extraction?.confidence === 'number' ? ` · ${t('rejected.confidence', { value: `${Math.round(extraction.confidence * 100)}%` })}` : ''}
          </p>
        ) : null}
        <button type="button" className="btn btn-ghost btn-sm" onClick={onDismiss}>
          {t('rejected.retry')}
        </button>
      </div>
    </div>
  );
}

/** Card for the 429 "you already reported this" response: points at the existing issue instead. */
export function DuplicateCard({ duplicate, onDismiss }: { duplicate: DuplicateSubmission; onDismiss: () => void }) {
  const { lang, t, tx, fmt } = useI18n();
  const { cluster_id: clusterId, created_at: createdAt } = duplicate.duplicate_of;
  const waitMin = Math.ceil(duplicate.retry_after_s / 60);
  return (
    <div className="banner banner-warn rejected" role="alert">
      <Icon name="merge" size={20} />
      <div>
        <strong>{lang === 'en' ? duplicate.message : t('apiError.duplicate_submission')}</strong>
        <p className="small">
          {createdAt ? t('duplicate.earlierAgo', { time: fmt.timeAgo(createdAt) }) : t('duplicate.earlier')}{' '}
          {clusterId ? tx('duplicate.follow', { link: <Link to={`/clusters/${clusterId}`}>{t('duplicate.open', { id: clusterId })}</Link> }) : t('duplicate.findOnMap')}
        </p>
        {waitMin > 0 ? <p className="small muted">{t('duplicate.wait', { minutes: fmt.count('minute', waitMin) })}</p> : null}
        <button type="button" className="btn btn-ghost btn-sm" onClick={onDismiss}>
          {t('common.dismiss')}
        </button>
      </div>
    </div>
  );
}
