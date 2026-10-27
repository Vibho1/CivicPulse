import type { Verification } from '../api';
import { mediaUrl } from '../api';
import { fmtDate, humanize, shortId } from '../lib/format';
import { verdictHeadline, verdictTone } from '../lib/status';
import { Icon } from './Icon';
import { VerdictBadge } from './ui';

interface Props {
  verification: Verification;
  /** Large, attention-grabbing variant used right after an action. */
  prominent?: boolean;
  onDismiss?: () => void;
}

function ConfidenceBar({ label, value }: { label: string; value: number }) {
  const pctv = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="conf">
      <div className="conf-head">
        <span>{label}</span>
        <strong>{pctv}%</strong>
      </div>
      <div className="conf-track">
        <div className="conf-fill" style={{ width: `${pctv}%` }} />
      </div>
    </div>
  );
}

export function VerificationCard({ verification: v, prominent = false, onDismiss }: Props) {
  const tone = verdictTone(v.verdict);
  const matched = v.details?.matched_cues ?? [];
  const mismatched = v.details?.mismatch_cues ?? [];
  const before = (v.before_photo_urls ?? []).map((u) => mediaUrl(u)).filter((u): u is string => !!u);
  const after = mediaUrl(v.photo_url);
  const kindLabel = v.kind === 'official_closure' ? 'Official closure check' : 'Citizen verification';
  const icon = tone === 'good' ? 'check-circle' : tone === 'bad' ? 'alert' : tone === 'warn' ? 'eye' : 'info';

  return (
    <article className={`verdict tone-${tone}${prominent ? ' verdict-prominent' : ''}`} aria-label={`${kindLabel}: ${v.verdict}`}>
      <header className="verdict-head">
        <div className="verdict-icon">
          <Icon name={icon} size={prominent ? 26 : 20} />
        </div>
        <div className="verdict-title">
          <div className="verdict-kind">
            {kindLabel}
            <span className="muted"> · {fmtDate(v.created_at)}</span>
          </div>
          <VerdictBadge verdict={v.verdict} size={prominent ? 'lg' : 'md'} />
          {prominent ? <h3>{verdictHeadline(v.verdict)}</h3> : null}
        </div>
        {onDismiss ? (
          <button type="button" className="icon-btn" aria-label="Dismiss" onClick={onDismiss}>
            <Icon name="x" size={16} />
          </button>
        ) : null}
      </header>

      <p className="verdict-explanation">{v.explanation}</p>

      {(before.length > 0 || after) && (
        <div className="verdict-photos">
          {before.slice(0, 1).map((u) => (
            <figure key={u}>
              <img src={u} alt="Before: citizen report photo" loading="lazy" />
              <figcaption>Before (citizen)</figcaption>
            </figure>
          ))}
          {after ? (
            <figure>
              <img src={after} alt={v.kind === 'official_closure' ? 'After: official closure photo' : 'Citizen proof photo'} loading="lazy" />
              <figcaption>{v.kind === 'official_closure' ? 'After (official)' : 'Proof (citizen)'}</figcaption>
            </figure>
          ) : (
            <figure className="no-photo">
              <div className="no-photo-box">
                <Icon name="camera" size={22} />
                <span>No after-photo</span>
              </div>
              <figcaption>After (official)</figcaption>
            </figure>
          )}
        </div>
      )}

      {(matched.length > 0 || mismatched.length > 0) && (
        <div className="cues">
          {matched.length > 0 && (
            <div>
              <div className="cues-label">Matched cues</div>
              <div className="chips">
                {matched.map((c) => (
                  <span key={c} className="chip chip-ok">
                    <Icon name="check" size={12} /> {c}
                  </span>
                ))}
              </div>
            </div>
          )}
          {mismatched.length > 0 && (
            <div>
              <div className="cues-label">Mismatches</div>
              <div className="chips">
                {mismatched.map((c) => (
                  <span key={c} className="chip chip-bad">
                    <Icon name="x" size={12} /> {c}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="verdict-meta">
        <ConfidenceBar label="Same location" value={v.same_location_confidence} />
        <ConfidenceBar label="Issue resolved" value={v.resolution_confidence} />
        <div className="verdict-facts">
          <span className="chip chip-muted">Fix quality: {humanize(v.fix_quality)}</span>
          <span className="chip chip-muted">By {shortId(v.actor)}</span>
          <span className="chip chip-muted" title="Which engine produced this verdict">
            {v.ai_mode.startsWith('gemini') ? 'Gemini vision' : v.ai_mode === 'seed' ? 'Demo data' : v.ai_mode === 'rule' ? 'Rule' : humanize(v.ai_mode)}
          </span>
        </div>
        {v.note ? (
          <p className="verdict-note">
            <strong>Note:</strong> {v.note}
          </p>
        ) : null}
      </div>
    </article>
  );
}
