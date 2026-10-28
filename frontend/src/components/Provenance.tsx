import type { PhotoFlag, Report } from '../api';
import { useI18n } from '../i18n';
import { fmtConfidence } from '../lib/format';
import { credibilityTone, photoFlagInfo } from '../lib/status';
import { Icon } from './Icon';

/** "Credibility 72%": how this reporter's earlier reports held up. Nothing for anonymous reporters. */
export function CredibilityChip({ value }: { value: number | null | undefined }) {
  const { t } = useI18n();
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return (
    <span className={`chip chip-${credibilityTone(value)}`} title={t('credibility.hint')}>
      {t('credibility.value', { value: fmtConfidence(value) })}
    </span>
  );
}

/** Server-side photo provenance flags (no EXIF, GPS far from the pin, stock/screenshot, blurred) as chips. */
export function PhotoFlagChips({ flags, blurred = 0 }: { flags: readonly (PhotoFlag | string)[] | null | undefined; blurred?: number }) {
  const { t, tn, has, label } = useI18n();
  if (!flags?.length) return null;
  return (
    <>
      {flags.map((f) => {
        const info = photoFlagInfo(f);
        const hint = has(`photoFlagHint.${f}`) ? t(`photoFlagHint.${f}`) : info.title;
        const title = f === 'faces_or_plates_blurred' && blurred > 0 ? tn('privacy.blurred', blurred) : hint;
        return (
          <span key={f} className={`chip chip-${info.tone}`} title={title || undefined}>
            <Icon name={info.icon} size={12} /> {label('photoFlag', f, info.label)}
          </span>
        );
      })}
    </>
  );
}

/**
 * One chip row with what CivicPulse knows about a report's evidence: the parsed
 * size estimate, photo provenance flags and (optionally) reporter credibility.
 * Renders nothing when there is nothing to show.
 */
export function ReportProvenance({ report, credibility = false, size = true }: { report: Report; credibility?: boolean; size?: boolean }) {
  const { t, fmt } = useI18n();
  const dims = size ? fmt.dimensions(report.parsed?.estimated_dimensions_cm) : null;
  const flags = report.photo_flags ?? [];
  const cred = credibility && typeof report.reporter_credibility === 'number';
  if (!dims && !flags.length && !cred) return null;
  return (
    <div className="chips">
      {dims ? (
        <span className="chip chip-muted" title={t('dims.hint')}>
          {dims}
        </span>
      ) : null}
      <PhotoFlagChips flags={flags} blurred={report.privacy_blurred ?? 0} />
      {cred ? <CredibilityChip value={report.reporter_credibility} /> : null}
    </div>
  );
}
