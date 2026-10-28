import { readPhotoExif, type PhotoExif } from './exif';

export interface PreparedPhoto {
  blob: Blob;
  url: string;
  width: number;
  height: number;
  originalName: string;
  originalBytes: number;
  /** EXIF presence / GPS of the ORIGINAL file (the re-encoded `blob` has none). */
  exif: PhotoExif;
}

async function loadBitmap(file: Blob): Promise<ImageBitmap | HTMLImageElement> {
  if (typeof createImageBitmap === 'function') {
    try {
      // 'from-image' honours EXIF orientation so phone photos are not sideways.
      return await createImageBitmap(file, { imageOrientation: 'from-image' });
    } catch {
      // fall through to the <img> path (older Safari)
    }
  }
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Could not read this image.'));
    };
    img.src = url;
  });
}

/**
 * Downscale an image to `maxSide` px on its longest edge and re-encode as JPEG.
 * Keeps uploads small on mobile data; the backend normalises again anyway.
 * The re-encode drops all metadata, so the original's EXIF (presence + GPS) is
 * read first and returned as `exif` for the caller to send alongside.
 */
export async function preparePhoto(file: File | Blob, maxSide = 1280, quality = 0.85): Promise<PreparedPhoto> {
  // readPhotoExif never rejects; it only looks at the original file's bytes.
  const [exif, source] = await Promise.all([readPhotoExif(file), loadBitmap(file)]);
  const srcW = source.width;
  const srcH = source.height;
  const scale = Math.min(1, maxSide / Math.max(srcW, srcH));
  const w = Math.max(1, Math.round(srcW * scale));
  const h = Math.max(1, Math.round(srcH * scale));

  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  let blob: Blob | null = null;
  if (ctx) {
    ctx.drawImage(source, 0, 0, w, h);
    blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
  }
  if ('close' in source) source.close();
  const out = blob ?? file;
  return {
    blob: out,
    url: URL.createObjectURL(out),
    width: w,
    height: h,
    originalName: file instanceof File ? file.name : 'photo.jpg',
    originalBytes: file.size,
    exif,
  };
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
