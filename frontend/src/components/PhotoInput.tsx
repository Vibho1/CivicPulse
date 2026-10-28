import { useEffect, useId, useRef, useState, type ChangeEvent } from 'react';
import { useI18n } from '../i18n';
import type { PhotoExif } from '../lib/exif';
import { fmtBytes, preparePhoto, type PreparedPhoto } from '../lib/image';
import { Icon } from './Icon';
import { Spinner } from './ui';

interface Props {
  value: PreparedPhoto | null;
  onChange: (photo: PreparedPhoto | null) => void;
  /** Defaults to the translated "Photo". */
  label?: string;
  hint?: string;
  /** Tap target copy for the camera button. */
  captureLabel?: string;
  disabled?: boolean;
}

/** What the original file's EXIF said; the caller sends it with the upload. */
function ExifChip({ exif }: { exif: PhotoExif }) {
  const { t } = useI18n();
  if (exif.lat !== undefined && exif.lng !== undefined) {
    return (
      <span className="chip chip-ok" title={t('photo.gpsTitle', { coords: `${exif.lat.toFixed(5)}, ${exif.lng.toFixed(5)}` })}>
        <Icon name="pin" size={12} /> {t('photo.gpsFound')}
      </span>
    );
  }
  if (exif.present) {
    return (
      <span className="chip chip-muted" title={t('photo.noGpsTitle')}>
        {t('photo.noGps')}
      </span>
    );
  }
  return (
    <span className="chip chip-muted" title={t('photo.noMetaTitle')}>
      {t('photo.noMeta')}
    </span>
  );
}

/**
 * Camera / gallery picker that downscales to ≤1280px JPEG on the client before
 * upload (keeps mobile uploads small; EXIF is stripped as a side-effect, so its
 * presence and GPS are read from the original first — see `PreparedPhoto.exif`).
 */
export function PhotoInput({ value, onChange, label, hint, captureLabel, disabled = false }: Props) {
  const { lang, t } = useI18n();
  const shownLabel = label ?? t('photo.label');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const galleryRef = useRef<HTMLInputElement>(null);
  const id = useId();

  // Revoke the preview URL when it is replaced/unmounted.
  useEffect(() => {
    const url = value?.url;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [value?.url]);

  async function handleFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setErr(null);
    setBusy(true);
    try {
      const prepared = await preparePhoto(file);
      onChange(prepared);
    } catch (ex) {
      setErr(lang === 'en' && ex instanceof Error ? ex.message : t('photo.readError'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="photo-input">
      <input ref={cameraRef} id={`${id}-camera`} type="file" accept="image/*" capture="environment" onChange={handleFile} hidden disabled={disabled} />
      <input ref={galleryRef} id={`${id}-gallery`} type="file" accept="image/*" onChange={handleFile} hidden disabled={disabled} />

      {value ? (
        <div className="photo-preview">
          <img src={value.url} alt={t('photo.previewAlt', { label: shownLabel })} />
          <div className="photo-preview-meta">
            <span>
              {value.width}×{value.height} · {fmtBytes(value.blob.size)}
              {value.originalBytes > value.blob.size * 1.2 ? <span className="muted"> {t('photo.was', { size: fmtBytes(value.originalBytes) })}</span> : null}{' '}
              <ExifChip exif={value.exif} />
            </span>
            <div className="row gap-s">
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => cameraRef.current?.click()} disabled={disabled || busy}>
                <Icon name="rotate" size={14} /> {t('photo.retake')}
              </button>
              <button type="button" className="btn btn-ghost btn-sm danger" onClick={() => onChange(null)} disabled={disabled || busy}>
                <Icon name="trash" size={14} /> {t('common.remove')}
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="photo-buttons">
          <button type="button" className="btn btn-secondary" onClick={() => cameraRef.current?.click()} disabled={disabled || busy}>
            {busy ? <Spinner size={16} /> : <Icon name="camera" size={16} />} {captureLabel ?? t('photo.capture')}
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => galleryRef.current?.click()} disabled={disabled || busy}>
            <Icon name="image" size={16} /> {t('photo.gallery')}
          </button>
        </div>
      )}
      {hint && !value ? <p className="hint">{hint}</p> : null}
      {err ? (
        <p className="field-error" role="alert">
          {err}
        </p>
      ) : null}
    </div>
  );
}
