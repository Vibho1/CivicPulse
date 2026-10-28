import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { ApiError, DEFAULT_LIMITS, api, duplicateSubmission, errorCode, errorMessage, type DuplicateSubmission, type Extraction, type ReportResponse } from '../api';
import { useApp } from '../context/AppContext';
import { Icon } from '../components/Icon';
import { LocationPicker, type LatLng } from '../components/LocationPicker';
import { PhotoInput } from '../components/PhotoInput';
import { DuplicateCard, RejectedCard, ReportResult } from '../components/ReportResult';
import { useToast } from '../components/Toast';
import { Spinner } from '../components/ui';
import { VoiceRecorder, extensionForMime, type AudioNote } from '../components/VoiceRecorder';
import { useI18n } from '../i18n';
import { exifFields } from '../lib/exif';
import type { PreparedPhoto } from '../lib/image';

/** Labels are `report.langHint.<id>`; `hint` is what the backend receives, so it stays English. */
const LANGUAGE_HINTS: { id: string; hint?: string }[] = [
  { id: 'auto' },
  { id: 'kn', hint: 'Kannada' },
  { id: 'en', hint: 'English' },
  { id: 'hi', hint: 'Hindi' },
  { id: 'kn-en', hint: 'Code-mixed Kannada and English (Kanglish)' },
];

interface Failure {
  message: string;
  extraction: Extraction | null;
  /** 422 `detail.code`, e.g. 'not_civic_issue' or 'low_confidence'. */
  code: string | null;
}

function ProgressCopy({ hasAudio, hasPhoto, gemini }: { hasAudio: boolean; hasPhoto: boolean; gemini: boolean }) {
  const { t } = useI18n();
  const steps = useMemo(() => {
    const s: string[] = [];
    if (gemini) {
      if (hasAudio) s.push(t('report.progress.listening'));
      if (hasPhoto) s.push(t('report.progress.looking'));
      s.push(t('report.progress.routing'));
    } else {
      s.push(t('report.progress.offline'));
    }
    s.push(t('report.progress.duplicates'), t('report.progress.scoring'));
    return s;
  }, [hasAudio, hasPhoto, gemini, t]);
  const [i, setI] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setI((x) => Math.min(x + 1, steps.length - 1)), 1700);
    return () => window.clearInterval(timer);
  }, [steps.length]);
  return <span>{steps[i]}</span>;
}

export default function ReportPage() {
  const { meta, health, reporterId } = useApp();
  const toast = useToast();
  const { lang, t, tx } = useI18n();

  const [loc, setLoc] = useState<LatLng | null>(null);
  const [accuracy, setAccuracy] = useState<number | null>(null);
  const [locSource, setLocSource] = useState<'gps' | 'preset' | 'manual' | null>(null);
  const [audio, setAudio] = useState<AudioNote | null>(null);
  const [text, setText] = useState('');
  const [langHint, setLangHint] = useState('auto');
  const [photo, setPhoto] = useState<PreparedPhoto | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [duplicate, setDuplicate] = useState<DuplicateSubmission | null>(null);
  const [result, setResult] = useState<ReportResponse | null>(null);

  // Desktop demos have no GPS: default to the first preset once meta arrives.
  useEffect(() => {
    if (!loc && meta?.demo_locations?.length) {
      const p = meta.demo_locations[0];
      setLoc({ lat: p.lat, lng: p.lng });
      setLocSource('preset');
    }
  }, [meta, loc]);

  const hasContent = Boolean(audio || photo || text.trim());
  const canSubmit = Boolean(loc) && hasContent && !submitting;
  const gemini = health?.ai_mode === 'gemini';

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!loc) {
      toast.error(t('report.toast.noLocation'));
      return;
    }
    if (!hasContent) {
      toast.error(t('report.toast.noContent'));
      return;
    }
    setSubmitting(true);
    setFailure(null);
    setDuplicate(null);
    try {
      const hint = LANGUAGE_HINTS.find((h) => h.id === langHint)?.hint;
      const res = await api.createReport({
        lat: loc.lat,
        lng: loc.lng,
        accuracy,
        text: text.trim() || undefined,
        reporter_id: reporterId,
        language_hint: hint,
        audio: audio ? { blob: audio.blob, filename: `note.${extensionForMime(audio.mimeType)}` } : undefined,
        photo: photo ? { blob: photo.blob, filename: 'photo.jpg' } : undefined,
        // Read from the original file: the resized upload has no EXIF left.
        ...exifFields(photo?.exif),
      });
      setResult(res);
      window.scrollTo({ top: 0, behavior: 'smooth' });
      toast.success(res.merged ? t('report.toast.merged', { id: res.cluster.id }) : t('report.toast.created', { id: res.cluster.id }));
    } catch (err) {
      const dup = duplicateSubmission(err);
      if (dup) {
        setDuplicate(dup);
      } else if (err instanceof ApiError && err.status === 422 && errorCode(err) === 'audio_too_long') {
        // English keeps the server's exact wording; other languages use the translated limit.
        toast.error(lang === 'en' ? err.message : t('apiError.audio_too_long', { seconds: meta?.limits?.max_audio_s ?? DEFAULT_LIMITS.max_audio_s }));
      } else if (err instanceof ApiError && err.status === 422) {
        setFailure({ message: err.message, extraction: err.extraction, code: errorCode(err) });
      } else {
        toast.error(errorMessage(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  function resetForm() {
    if (audio?.url) URL.revokeObjectURL(audio.url);
    setResult(null);
    setFailure(null);
    setDuplicate(null);
    setAudio(null);
    setText('');
    setPhoto(null);
    setLangHint('auto');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  if (result) {
    return (
      <div className="page narrow">
        <ReportResult result={result} onReset={resetForm} />
      </div>
    );
  }

  const parts = [audio && t('report.part.voice'), photo && t('report.part.photo'), text.trim() && t('report.part.text')].filter(Boolean).join(' + ');

  return (
    <div className="page narrow">
      <header className="page-head">
        <h1>{t('report.title')}</h1>
        <p className="muted">{t('report.subtitle')}</p>
      </header>

      <form className="wizard" onSubmit={(e) => void submit(e)} noValidate>
        <section className="card form-section" aria-labelledby="sec-location">
          <div className="section-head">
            <span className="step">1</span>
            <div>
              <h2 id="sec-location">{t('report.where')}</h2>
              <p className="muted small">{t('report.whereHint')}</p>
            </div>
          </div>
          <LocationPicker
            value={loc}
            accuracy={accuracy}
            source={locSource}
            onChange={(ll, acc, src) => {
              setLoc(ll);
              setAccuracy(acc);
              setLocSource(src);
            }}
            wards={meta?.wards ?? []}
            presets={meta?.demo_locations ?? []}
            disabled={submitting}
          />
        </section>

        <section className="card form-section" aria-labelledby="sec-voice">
          <div className="section-head">
            <span className="step">2</span>
            <div>
              <h2 id="sec-voice">{t('report.voice')}</h2>
              <p className="muted small">{t('report.voiceHint')}</p>
            </div>
          </div>
          <VoiceRecorder value={audio} onChange={setAudio} disabled={submitting} />
        </section>

        <section className="card form-section" aria-labelledby="sec-text">
          <div className="section-head">
            <span className="step">3</span>
            <div>
              <h2 id="sec-text">
                {t('report.text')} <span className="muted">{t('common.optional')}</span>
              </h2>
              <p className="muted small">{t('report.textHint')}</p>
            </div>
          </div>
          <label className="field">
            <span className="sr-only">{t('report.textLabel')}</span>
            <textarea
              className="textarea"
              rows={3}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={t('report.textPlaceholder')}
              maxLength={1000}
              disabled={submitting}
            />
          </label>
          <label className="field field-row">
            <span className="field-label">{t('report.langHintLabel')}</span>
            <select className="select" value={langHint} onChange={(e) => setLangHint(e.target.value)} disabled={submitting}>
              {LANGUAGE_HINTS.map((l) => (
                <option key={l.id} value={l.id}>
                  {t(`report.langHint.${l.id}`)}
                </option>
              ))}
            </select>
          </label>
        </section>

        <section className="card form-section" aria-labelledby="sec-photo">
          <div className="section-head">
            <span className="step">4</span>
            <div>
              <h2 id="sec-photo">
                {t('report.photo')} <span className="muted">{t('common.recommended')}</span>
              </h2>
              <p className="muted small">{t('report.photoHint')}</p>
            </div>
          </div>
          <PhotoInput
            value={photo}
            onChange={setPhoto}
            label={t('report.photoLabel')}
            hint={health?.features?.face_blur ? t('report.photoResizeBlur') : t('report.photoResize')}
            disabled={submitting}
          />
        </section>

        {duplicate ? <DuplicateCard duplicate={duplicate} onDismiss={() => setDuplicate(null)} /> : null}
        {failure ? <RejectedCard message={failure.message} extraction={failure.extraction} code={failure.code} onDismiss={() => setFailure(null)} /> : null}

        <div className="submit-bar card">
          <div className="submit-info">
            {!loc ? (
              <span className="muted">{t('report.needLocation')}</span>
            ) : !hasContent ? (
              <span className="muted">{t('report.needContent')}</span>
            ) : (
              <span className="muted">
                {tx('report.filingAs', { id: <code>{reporterId}</code> })} · {parts}
              </span>
            )}
            <p className="emergency-note small">
              <Icon name="phone" size={13} /> {tx('emergency.note', { call: <a href="tel:112">{t('emergency.call', { number: '112' })}</a> })}
            </p>
          </div>
          <button type="submit" className="btn btn-primary btn-lg" disabled={!canSubmit}>
            {submitting ? (
              <>
                <Spinner size={18} /> <ProgressCopy hasAudio={!!audio} hasPhoto={!!photo} gemini={gemini} />
              </>
            ) : (
              <>
                <Icon name="send" size={18} /> {t('report.submit')}
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
