import type { Verification } from '../api';
import { DEFAULT_LIMITS, mediaUrl } from '../api';
import { useApp } from '../context/AppContext';
import { useI18n } from '../i18n';
import { fmtDate, humanize, shortId } from '../lib/format';
import { repairQualityLabel, repairQualityTone, verdictHeadline, verdictTone } from '../lib/status';
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

/** Proof-photo GPS vs the reported spot. Nothing for photo-less closures or pre-check verifications. */
function GpsChip({ v, radiusM }: { v: Verification; radiusM: number }) {
  const { t, fmt } = useI18n();
  if (!v.photo_url || v.gps_source === undefined) return null;
  const source = v.gps_source ?? null;
  const distance = v.gps_distance_m ?? null;
  if (!source || distance === null) {
    return (
      <span className="chip chip-muted" title={t('verification.noGpsTitle')}>
        {t('verification.noGps')}
      </span>
    );
  }
  // GPS evidence only; whether the picture itself matches is the verdict's job.
  const ok = distance <= radiusM;
  return (
    <span className={`chip ${ok ? 'chip-ok' : 'chip-bad'}`} title={t('verification.gpsTitle', { radius: fmt.distance(radiusM) })}>
      <Icon name="pin" size={12} />{' '}
      {t('verification.gps', { distance: fmt.distance(distance), source: source === 'exif' ? t('verification.source.exif') : t('verification.source.device') })}
    </span>
  );
}

export function VerificationCard({ verification: v, prominent = false, onDismiss }: Props) {
  const { meta } = useApp();
  const { t, label } = useI18n();
  const gpsRadiusM = meta?.limits?.verify_gps_radius_m ?? DEFAULT_LIMITS.verify_gps_radius_m;
  const repairQuality = v.repair_quality ?? null;
  const tone = verdictTone(v.verdict);
  const matched = v.details?.matched_cues ?? [];
  const mismatched = v.details?.mismatch_cues ?? [];
  const before = (v.before_photo_urls ?? []).map((u) => mediaUrl(u)).filter((u): u is string => !!u);
  const after = mediaUrl(v.photo_url);
  const official = v.kind === 'official_closure';
  const kindLabel = official ? t('verification.kind.official_closure') : t('verification.kind.citizen');
  const icon = tone === 'good' ? 'check-circle' : tone === 'bad' ? 'alert' : tone === 'warn' ? 'eye' : 'info';
  const engine = v.ai_mode.startsWith('gemini')
    ? t('verification.engine.gemini')
    : v.ai_mode === 'seed'
      ? t('verification.engine.seed')
      : v.ai_mode === 'rule'
        ? t('verification.engine.rule')
        : humanize(v.ai_mode);

  return (
    <article className={`verdict tone-${tone}${prominent ? ' verdict-prominent' : ''}`} aria-label={`${kindLabel}: ${label('verdict', v.verdict, v.verdict)}`}>
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
          {prominent ? <h3>{label('verdictHeadline', v.verdict, verdictHeadline(v.verdict))}</h3> : null}
        </div>
        {onDismiss ? (
          <button type="button" className="icon-btn" aria-label={t('common.dismiss')} onClick={onDismiss}>
            <Icon name="x" size={16} />
          </button>
        ) : null}
      </header>

      <p className="verdict-explanation">{v.explanation}</p>

      {(before.length > 0 || after) && (
        <div className="verdict-photos">
          {before.slice(0, 1).map((u) => (
            <figure key={u}>
              <img src={u} alt={t('photos.beforeAlt')} loading="lazy" />
              <figcaption>{t('verification.beforeCitizen')}</figcaption>
            </figure>
          ))}
          {after ? (
            <figure>
              <img src={after} alt={official ? t('photos.afterAlt') : t('photos.proofAlt')} loading="lazy" />
              <figcaption>{official ? t('verification.afterOfficial') : t('verification.proofCitizen')}</figcaption>
            </figure>
          ) : (
            <figure className="no-photo">
              <div className="no-photo-box">
                <Icon name="camera" size={22} />
                <span>{t('verification.noAfterPhoto')}</span>
              </div>
              <figcaption>{t('verification.afterOfficial')}</figcaption>
            </figure>
          )}
        </div>
      )}

      {(matched.length > 0 || mismatched.length > 0) && (
        <div className="cues">
          {matched.length > 0 && (
            <div>
              <div className="cues-label">{t('verification.matched')}</div>
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
              <div className="cues-label">{t('verification.mismatches')}</div>
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
        <ConfidenceBar label={t('verification.sameLocation')} value={v.same_location_confidence} />
        <ConfidenceBar label={t('verification.issueResolved')} value={v.resolution_confidence} />
        <div className="verdict-facts">
          <GpsChip v={v} radiusM={gpsRadiusM} />
          {repairQuality ? (
            <span className={`chip chip-${repairQualityTone(repairQuality)}`} title={t('verification.repairQuality')}>
              {label('repairQuality', repairQuality, repairQualityLabel(repairQuality))}
            </span>
          ) : null}
          <span className="chip chip-muted">{t('verification.fixQuality', { quality: label('fixQuality', v.fix_quality, humanize(v.fix_quality)) })}</span>
          <span className="chip chip-muted">{t('verification.by', { actor: shortId(v.actor) })}</span>
          <span className="chip chip-muted" title={t('verification.engineTitle')}>
            {engine}
          </span>
        </div>
        {v.note ? (
          <p className="verdict-note">
            <strong>{t('verification.note')}</strong> {v.note}
          </p>
        ) : null}
      </div>
    </article>
  );
}
