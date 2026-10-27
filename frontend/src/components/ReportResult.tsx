import { Link } from 'react-router-dom';
import { mediaUrl, type Extraction, type ReportResponse } from '../api';
import { coordText, fmtDate, humanize, languageLabel } from '../lib/format';
import { Icon } from './Icon';
import { AgencyChip, LanguageBadge, ScoreBreakdownBars, ScoreRing, SeverityMeter, StatusBadge } from './ui';

interface Props {
  result: ReportResponse;
  onReset: () => void;
}

function Banner({ result }: { result: ReportResponse }) {
  const { cluster, merged, reopened, repeat_failure, previous_cluster } = result;
  if (repeat_failure) {
    const when = previous_cluster?.verified_at ?? previous_cluster?.resolved_at ?? null;
    return (
      <div className="banner banner-bad" role="status">
        <Icon name="flag" size={20} />
        <div>
          <strong>Repeat failure.</strong> This spot was marked fixed{when ? ` on ${fmtDate(when, { time: false })}` : ' recently'} and has failed again within 180 days — flagged for a
          warranty / defect-liability review.
          {previous_cluster ? (
            <>
              {' '}
              <Link to={`/clusters/${previous_cluster.id}`}>Previous issue {previous_cluster.id}</Link>
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
          <strong>Reopened a disputed closure.</strong> {cluster.id} had been marked resolved; your report puts it back in front of the agency with the community's evidence.
        </div>
      </div>
    );
  }
  if (merged) {
    return (
      <div className="banner banner-info" role="status">
        <Icon name="merge" size={20} />
        <div>
          <strong>Merged into existing issue {cluster.id}</strong> — now {cluster.report_count} reports. More voices, higher impact score.
        </div>
      </div>
    );
  }
  return (
    <div className="banner banner-good" role="status">
      <Icon name="check-circle" size={20} />
      <div>
        <strong>New issue created: {cluster.id}.</strong> It is now on the live map and routed to {cluster.agency_short}.
      </div>
    </div>
  );
}

export function ReportResult({ result, onReset }: Props) {
  const { report, cluster, extraction, ai_mode, location_warning } = result;
  const transcript = report.transcript?.trim();
  const english = report.transcript_english?.trim();
  const hazards = report.hazards?.length ? report.hazards : cluster.hazards;
  const ev = report.evidence ?? {};
  const photo = mediaUrl(report.photo_url);
  const gemini = ai_mode.startsWith('gemini');

  return (
    <section className="result card" aria-label="Report result">
      <Banner result={result} />
      {location_warning ? (
        <div className="banner banner-warn" role="note">
          <Icon name="alert" size={18} />
          <div>{location_warning}</div>
        </div>
      ) : null}

      <header className="result-head">
        <div>
          <div className="eyebrow">Report {report.id}</div>
          <h2>{report.title || cluster.title}</h2>
          <div className="chips">
            <span className="chip chip-info">{report.category_label}</span>
            <LanguageBadge code={report.language} />
            <StatusBadge status={cluster.status} size="sm" />
            {report.landmark ? (
              <span className="chip chip-muted">
                <Icon name="pin" size={12} /> {report.landmark}
              </span>
            ) : null}
          </div>
        </div>
        {photo ? <img className="result-photo" src={photo} alt="Your report photo" /> : null}
      </header>

      <div className="result-grid">
        <div className="result-col">
          {(transcript || english) && (
            <div className="block">
              <div className="block-title">
                <Icon name="mic" size={15} /> What you said
              </div>
              {transcript ? (
                <blockquote className="transcript" lang={report.language?.split('-')[0] || undefined}>
                  “{transcript}”
                </blockquote>
              ) : null}
              {english && english !== transcript ? (
                <p className="translation">
                  {transcript ? <span className="muted">English: </span> : null}
                  {english}
                </p>
              ) : null}
              {report.description && report.description !== english ? <p className="muted small">Engineer summary: {report.description}</p> : null}
            </div>
          )}

          <div className="block">
            <div className="block-title">
              <Icon name="alert" size={15} /> Severity
            </div>
            <SeverityMeter severity={report.severity} />
            {report.size_estimate ? <p className="muted small">Size: {report.size_estimate}</p> : null}
          </div>

          <div className="routing routing-hero">
            <div className="routing-head">
              <Icon name="send" size={18} />
              <span>Routed to</span>
            </div>
            <div className="routing-agency">{cluster.agency_label}</div>
            <p className="routing-reason">{report.agency_reason || cluster.agency_reason || extraction.agency_reasoning || 'Default routing for this category.'}</p>
            <div className="chips">
              <AgencyChip short={cluster.agency_short} label={cluster.agency_label} />
              <span className="chip chip-muted">Helpline {cluster.agency_info.helpline}</span>
              <span className="chip chip-muted">{cluster.agency_info.x_handle}</span>
            </div>
          </div>

          {(hazards.length > 0 || ev.recent_digging || (ev.utility_work_type && ev.utility_work_type !== 'none')) && (
            <div className="block">
              <div className="block-title">
                <Icon name="zap" size={15} /> Hazards &amp; evidence
              </div>
              <div className="chips">
                {hazards.map((h) => (
                  <span key={h} className="chip chip-warn">
                    {humanize(h)}
                  </span>
                ))}
                {ev.recent_digging ? (
                  <span className="chip chip-bad">
                    <Icon name="alert" size={12} /> Recent digging
                  </span>
                ) : null}
                {ev.utility_work_type && ev.utility_work_type !== 'none' ? <span className="chip chip-bad">Utility work: {humanize(ev.utility_work_type)}</span> : null}
              </div>
            </div>
          )}

          {ev.photo_provided ? (
            <div className="block">
              <div className="block-title">
                <Icon name="image" size={15} /> Photo check
              </div>
              <div className="chips">
                <span className={`chip ${ev.photo_usable ? 'chip-ok' : 'chip-warn'}`}>{ev.photo_usable ? 'Photo usable' : 'Photo unclear'}</span>
                <span className={`chip ${ev.photo_matches_description === false ? 'chip-warn' : 'chip-ok'}`}>
                  {ev.photo_matches_description === false ? 'Does not match description' : 'Matches description'}
                </span>
                {ev.people_or_plates_visible ? (
                  <span className="chip chip-warn" title="Faces or number plates are readable; consider re-taking the photo.">
                    Faces / plates visible
                  </span>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>

        <div className="result-col">
          <div className="block impact-block">
            <div className="block-title">
              <Icon name="activity" size={15} /> Impact score
            </div>
            <div className="impact-row">
              <ScoreRing score={cluster.impact_score} size={88} stroke={9} showLabel />
              <div className="impact-text">
                <div>
                  <strong>{cluster.report_count}</strong> report{cluster.report_count === 1 ? '' : 's'} · max severity <strong>{cluster.max_severity}/5</strong>
                </div>
                <div className="muted small">
                  {cluster.ward}
                  {cluster.zone ? ` · ${cluster.zone}` : ''} · {coordText(cluster.lat, cluster.lng)}
                </div>
                <div className="muted small">SLA target {cluster.sla_hours} h</div>
              </div>
            </div>
            <ScoreBreakdownBars cluster={cluster} />
          </div>

          <p className="ai-note">
            <Icon name={gemini ? 'spark' : 'info'} size={14} />
            {gemini ? (
              <>
                Parsed by <strong>Gemini</strong> · confidence {Math.round((report.confidence ?? 0) * 100)}%
              </>
            ) : (
              <>
                Parsed <strong>offline (heuristic)</strong> — set <code>GEMINI_API_KEY</code> on the backend for transcription, translation and photo understanding.
              </>
            )}
          </p>
        </div>
      </div>

      <footer className="result-actions">
        <Link to={`/clusters/${cluster.id}`} className="btn btn-primary btn-lg">
          Open issue {cluster.id} <Icon name="chevron-right" size={16} />
        </Link>
        <button type="button" className="btn btn-ghost" onClick={onReset}>
          <Icon name="plus-circle" size={16} /> File another report
        </button>
      </footer>
    </section>
  );
}

/** Friendly card for the 422 "not a civic issue / low confidence" response. */
export function RejectedCard({ message, extraction, onDismiss }: { message: string; extraction: Extraction | null; onDismiss: () => void }) {
  const heard = extraction?.transcript?.trim() || extraction?.transcript_english?.trim() || '';
  return (
    <div className="banner banner-warn rejected" role="alert">
      <Icon name="info" size={20} />
      <div>
        <strong>{message}</strong>
        <p className="small">
          CivicPulse only files reports about public infrastructure — potholes, leaks, garbage, streetlights, drains, wires and the like. Try describing the problem and
          where it is, e.g. “streetlight not working near the bus stop”.
        </p>
        {heard ? (
          <p className="small muted">
            We understood: “{heard}”{extraction?.language ? ` · ${languageLabel(extraction.language)}` : ''}
            {typeof extraction?.confidence === 'number' ? ` · confidence ${Math.round(extraction.confidence * 100)}%` : ''}
          </p>
        ) : null}
        <button type="button" className="btn btn-ghost btn-sm" onClick={onDismiss}>
          Edit and try again
        </button>
      </div>
    </div>
  );
}
