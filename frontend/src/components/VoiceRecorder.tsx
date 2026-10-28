import { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { Icon } from './Icon';

export interface AudioNote {
  blob: Blob;
  mimeType: string;
  durationS: number;
  url: string;
}

const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4;codecs=mp4a.40.2', 'audio/mp4', 'audio/ogg;codecs=opus'];
/** PRD cap for voice notes; the API rejects longer clips (422 `audio_too_long`). */
const MAX_SECONDS = 30;
/** Auto-stop this much early so encoder latency never pushes a clip past the cap. */
const STOP_MARGIN_MS = 400;

export function pickRecorderMime(): string | null {
  if (typeof MediaRecorder === 'undefined') return null;
  for (const c of MIME_CANDIDATES) {
    try {
      if (MediaRecorder.isTypeSupported(c)) return c;
    } catch {
      /* ignore */
    }
  }
  return '';
}

export function extensionForMime(mime: string): string {
  const m = mime.toLowerCase();
  if (m.includes('webm')) return 'webm';
  if (m.includes('mp4') || m.includes('aac') || m.includes('m4a')) return 'm4a';
  if (m.includes('ogg')) return 'ogg';
  if (m.includes('wav')) return 'wav';
  return 'webm';
}

function fmtClock(s: number): string {
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${r.toString().padStart(2, '0')}`;
}

type Phase = 'idle' | 'requesting' | 'recording' | 'done' | 'unsupported';

interface Props {
  value: AudioNote | null;
  onChange: (note: AudioNote | null) => void;
  disabled?: boolean;
}

export function VoiceRecorder({ value, onChange, disabled = false }: Props) {
  const { lang, t } = useI18n();
  const [phase, setPhase] = useState<Phase>(() => (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia ? 'unsupported' : value ? 'done' : 'idle'));
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);
  const startedAtRef = useRef<number>(0);
  const mimeRef = useRef<string>('');

  const cleanupStream = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    void audioCtxRef.current?.close().catch(() => undefined);
    audioCtxRef.current = null;
    setLevel(0);
  }, []);

  useEffect(() => () => cleanupStream(), [cleanupStream]);

  // Keep phase in sync when the parent clears the note.
  useEffect(() => {
    if (!value && phase === 'done') setPhase('idle');
  }, [value, phase]);

  const stop = useCallback(() => {
    const rec = recorderRef.current;
    if (rec && rec.state !== 'inactive') rec.stop();
  }, []);

  async function start() {
    setError(null);
    setPhase('requesting');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      streamRef.current = stream;
      const mime = pickRecorderMime() ?? '';
      mimeRef.current = mime;
      const rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      recorderRef.current = rec;
      chunksRef.current = [];
      rec.ondataavailable = (e: BlobEvent) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = () => {
        const type = rec.mimeType || mimeRef.current || 'audio/webm';
        const blob = new Blob(chunksRef.current, { type });
        const durationS = Math.max(1, Math.round((Date.now() - startedAtRef.current) / 1000));
        cleanupStream();
        if (blob.size === 0) {
          setError(t('voice.empty'));
          setPhase('idle');
          return;
        }
        onChange({ blob, mimeType: type, durationS, url: URL.createObjectURL(blob) });
        setPhase('done');
      };
      rec.onerror = () => {
        setError(t('voice.failed'));
        cleanupStream();
        setPhase('idle');
      };

      // Live input level for the "is it hearing me?" hint.
      try {
        const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (Ctx) {
          const ctx = new Ctx();
          audioCtxRef.current = ctx;
          const src = ctx.createMediaStreamSource(stream);
          const analyser = ctx.createAnalyser();
          analyser.fftSize = 512;
          src.connect(analyser);
          const buf = new Uint8Array(analyser.fftSize);
          const tick = () => {
            analyser.getByteTimeDomainData(buf);
            let sum = 0;
            for (let i = 0; i < buf.length; i++) {
              const v = (buf[i] - 128) / 128;
              sum += v * v;
            }
            const rms = Math.sqrt(sum / buf.length);
            setLevel((prev) => Math.max(rms * 2.2, prev * 0.85));
            rafRef.current = requestAnimationFrame(tick);
          };
          rafRef.current = requestAnimationFrame(tick);
        }
      } catch {
        /* level meter is optional */
      }

      startedAtRef.current = Date.now();
      setSeconds(0);
      timerRef.current = window.setInterval(() => {
        const ms = Date.now() - startedAtRef.current;
        setSeconds(Math.min(MAX_SECONDS, Math.floor(ms / 1000)));
        if (ms >= MAX_SECONDS * 1000 - STOP_MARGIN_MS) stop();
      }, 250);
      rec.start(250);
      setPhase('recording');
    } catch (e) {
      cleanupStream();
      const name = e instanceof DOMException ? e.name : '';
      setError(
        name === 'NotAllowedError'
          ? t('voice.denied')
          : name === 'NotFoundError'
            ? t('voice.noMic')
            : lang === 'en' && e instanceof Error
              ? e.message
              : t('voice.startFailed'),
      );
      setPhase('idle');
    }
  }

  function discard() {
    if (value?.url) URL.revokeObjectURL(value.url);
    onChange(null);
    setPhase('idle');
    setSeconds(0);
  }

  if (phase === 'unsupported') {
    return (
      <div className="recorder recorder-unsupported">
        <Icon name="mic" size={18} />
        <span>{t('voice.unsupported')}</span>
      </div>
    );
  }

  if (phase === 'done' && value) {
    return (
      <div className="recorder recorder-done">
        <div className="recorder-row">
          <span className="chip chip-ok">
            <Icon name="check" size={13} /> {t('voice.note', { duration: fmtClock(value.durationS) })}
          </span>
          <span className="muted small">{value.mimeType.split(';')[0]}</span>
        </div>
        <audio controls src={value.url} className="audio-player" preload="metadata" />
        <div className="row gap-s">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void start()} disabled={disabled}>
            <Icon name="rotate" size={14} /> {t('voice.rerecord')}
          </button>
          <button type="button" className="btn btn-ghost btn-sm danger" onClick={discard} disabled={disabled}>
            <Icon name="trash" size={14} /> {t('common.remove')}
          </button>
        </div>
      </div>
    );
  }

  const recording = phase === 'recording';
  const bars = 14;
  return (
    <div className={`recorder${recording ? ' recording' : ''}`}>
      <div className="recorder-row">
        <button
          type="button"
          className={`rec-btn${recording ? ' rec-stop' : ''}`}
          onClick={() => (recording ? stop() : void start())}
          disabled={disabled || phase === 'requesting'}
          aria-pressed={recording}
          aria-label={recording ? t('voice.stop') : t('voice.start')}
        >
          <Icon name={recording ? 'stop' : 'mic'} size={22} />
        </button>
        <div className="recorder-status">
          <div className="recorder-time" aria-live="polite">
            {phase === 'requesting'
              ? t('voice.waiting')
              : recording
                ? t('voice.recording', { elapsed: fmtClock(seconds), max: fmtClock(MAX_SECONDS) })
                : t('voice.tapToRecord', { max: fmtClock(MAX_SECONDS) })}
          </div>
          <div className="level" aria-hidden="true">
            {Array.from({ length: bars }, (_, i) => {
              const threshold = (i + 1) / bars;
              const on = recording && level >= threshold * 0.9;
              return <span key={i} className={`level-bar${on ? ' on' : ''}`} style={{ height: `${30 + (i % 4) * 18}%` }} />;
            })}
          </div>
          <div className="hint">
            {recording ? (level > 0.08 ? t('voice.levelGood') : t('voice.levelLow')) : t('voice.hint')}
          </div>
        </div>
      </div>
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
