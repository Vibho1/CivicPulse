import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { ApiError, api, errorMessage, type Extraction, type ReportResponse } from '../api';
import { useApp } from '../context/AppContext';
import { Icon } from '../components/Icon';
import { LocationPicker, type LatLng } from '../components/LocationPicker';
import { PhotoInput } from '../components/PhotoInput';
import { RejectedCard, ReportResult } from '../components/ReportResult';
import { useToast } from '../components/Toast';
import { Spinner } from '../components/ui';
import { VoiceRecorder, extensionForMime, type AudioNote } from '../components/VoiceRecorder';
import type { PreparedPhoto } from '../lib/image';

const LANGUAGE_HINTS: { id: string; label: string; hint?: string }[] = [
  { id: 'auto', label: 'Auto-detect' },
  { id: 'kn', label: 'Kannada (ಕನ್ನಡ)', hint: 'Kannada' },
  { id: 'en', label: 'English', hint: 'English' },
  { id: 'hi', label: 'Hindi (हिन्दी)', hint: 'Hindi' },
  { id: 'kn-en', label: 'Code-mixed (Kannada + English)', hint: 'Code-mixed Kannada and English (Kanglish)' },
];

interface Failure {
  message: string;
  extraction: Extraction | null;
}

function ProgressCopy({ hasAudio, hasPhoto, gemini }: { hasAudio: boolean; hasPhoto: boolean; gemini: boolean }) {
  const steps = useMemo(() => {
    const s: string[] = [];
    if (gemini) {
      if (hasAudio) s.push('Gemini is listening to your voice note…');
      if (hasPhoto) s.push('Gemini is looking at your photo…');
      s.push('Working out the right agency…');
    } else {
      s.push('Parsing your report (offline mode)…');
    }
    s.push('Checking for nearby duplicate reports…', 'Scoring impact…');
    return s;
  }, [hasAudio, hasPhoto, gemini]);
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => setI((x) => Math.min(x + 1, steps.length - 1)), 1700);
    return () => window.clearInterval(t);
  }, [steps.length]);
  return <span>{steps[i]}</span>;
}

export default function ReportPage() {
  const { meta, health, reporterId } = useApp();
  const toast = useToast();

  const [loc, setLoc] = useState<LatLng | null>(null);
  const [accuracy, setAccuracy] = useState<number | null>(null);
  const [locSource, setLocSource] = useState<'gps' | 'preset' | 'manual' | null>(null);
  const [audio, setAudio] = useState<AudioNote | null>(null);
  const [text, setText] = useState('');
  const [langHint, setLangHint] = useState('auto');
  const [photo, setPhoto] = useState<PreparedPhoto | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
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
      toast.error('Pick a location first.');
      return;
    }
    if (!hasContent) {
      toast.error('Add a voice note, a photo or some text.');
      return;
    }
    setSubmitting(true);
    setFailure(null);
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
      });
      setResult(res);
      window.scrollTo({ top: 0, behavior: 'smooth' });
      toast.success(res.merged ? `Merged into ${res.cluster.id}` : `Issue ${res.cluster.id} created`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFailure({ message: err.message, extraction: err.extraction });
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

  return (
    <div className="page narrow">
      <header className="page-head">
        <h1>Report an issue</h1>
        <p className="muted">Speak, snap or type. Gemini transcribes, translates, classifies and routes it to the right agency — in seconds.</p>
      </header>

      <form className="wizard" onSubmit={(e) => void submit(e)} noValidate>
        <section className="card form-section" aria-labelledby="sec-location">
          <div className="section-head">
            <span className="step">1</span>
            <div>
              <h2 id="sec-location">Where is it?</h2>
              <p className="muted small">Your position, a demo preset, or tap the map.</p>
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
              <h2 id="sec-voice">Voice note</h2>
              <p className="muted small">Describe the problem in your own words and language.</p>
            </div>
          </div>
          <VoiceRecorder value={audio} onChange={setAudio} disabled={submitting} />
        </section>

        <section className="card form-section" aria-labelledby="sec-text">
          <div className="section-head">
            <span className="step">3</span>
            <div>
              <h2 id="sec-text">
                Text <span className="muted">(optional)</span>
              </h2>
              <p className="muted small">Add details, a landmark, or type instead of speaking.</p>
            </div>
          </div>
          <label className="field">
            <span className="sr-only">Describe the issue</span>
            <textarea
              className="textarea"
              rows={3}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder='e.g. "ORR service lane alli dodda gundi ide, near Ecospace"'
              maxLength={1000}
              disabled={submitting}
            />
          </label>
          <label className="field field-row">
            <span className="field-label">Language hint</span>
            <select className="select" value={langHint} onChange={(e) => setLangHint(e.target.value)} disabled={submitting}>
              {LANGUAGE_HINTS.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.label}
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
                Photo <span className="muted">(recommended)</span>
              </h2>
              <p className="muted small">A clear photo lets Gemini judge severity, spot utility digging, and verify the fix later.</p>
            </div>
          </div>
          <PhotoInput value={photo} onChange={setPhoto} label="Issue photo" hint="Resized to 1280px on your phone before upload. Avoid faces and number plates." disabled={submitting} />
        </section>

        {failure ? <RejectedCard message={failure.message} extraction={failure.extraction} onDismiss={() => setFailure(null)} /> : null}

        <div className="submit-bar card">
          <div className="submit-info">
            {!loc ? (
              <span className="muted">Pick a location to continue.</span>
            ) : !hasContent ? (
              <span className="muted">Add a voice note, photo or text.</span>
            ) : (
              <span className="muted">
                Filing as <code>{reporterId}</code> · {[audio && 'voice', photo && 'photo', text.trim() && 'text'].filter(Boolean).join(' + ')}
              </span>
            )}
          </div>
          <button type="submit" className="btn btn-primary btn-lg" disabled={!canSubmit}>
            {submitting ? (
              <>
                <Spinner size={18} /> <ProgressCopy hasAudio={!!audio} hasPhoto={!!photo} gemini={gemini} />
              </>
            ) : (
              <>
                <Icon name="send" size={18} /> Submit report
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
