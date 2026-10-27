import { useEffect, useId, useRef, useState, type ChangeEvent } from 'react';
import { fmtBytes, preparePhoto, type PreparedPhoto } from '../lib/image';
import { Icon } from './Icon';
import { Spinner } from './ui';

interface Props {
  value: PreparedPhoto | null;
  onChange: (photo: PreparedPhoto | null) => void;
  label?: string;
  hint?: string;
  /** Tap target copy for the camera button. */
  captureLabel?: string;
  disabled?: boolean;
}

/**
 * Camera / gallery picker that downscales to ≤1280px JPEG on the client before
 * upload (keeps mobile uploads small; EXIF is stripped as a side-effect).
 */
export function PhotoInput({ value, onChange, label = 'Photo', hint, captureLabel = 'Take photo', disabled = false }: Props) {
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
      setErr(ex instanceof Error ? ex.message : 'Could not read this image.');
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
          <img src={value.url} alt={`${label} preview`} />
          <div className="photo-preview-meta">
            <span>
              {value.width}×{value.height} · {fmtBytes(value.blob.size)}
              {value.originalBytes > value.blob.size * 1.2 ? <span className="muted"> (was {fmtBytes(value.originalBytes)})</span> : null}
            </span>
            <div className="row gap-s">
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => cameraRef.current?.click()} disabled={disabled || busy}>
                <Icon name="rotate" size={14} /> Retake
              </button>
              <button type="button" className="btn btn-ghost btn-sm danger" onClick={() => onChange(null)} disabled={disabled || busy}>
                <Icon name="trash" size={14} /> Remove
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="photo-buttons">
          <button type="button" className="btn btn-secondary" onClick={() => cameraRef.current?.click()} disabled={disabled || busy}>
            {busy ? <Spinner size={16} /> : <Icon name="camera" size={16} />} {captureLabel}
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => galleryRef.current?.click()} disabled={disabled || busy}>
            <Icon name="image" size={16} /> Choose from gallery
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
