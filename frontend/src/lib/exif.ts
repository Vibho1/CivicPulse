/**
 * Minimal, dependency-free EXIF reader: does the original photo carry EXIF at
 * all, and where was it taken (GPS IFD)?
 *
 * Photos are re-encoded through a canvas before upload (see image.ts), which
 * strips every bit of metadata. So we read the ORIGINAL file's bytes first and
 * send what we found as `photo_exif` / `photo_lat` / `photo_lng`: the server
 * flags forwarded/stock photos (no EXIF) and photos taken far from the pin, and
 * prefers EXIF GPS over the device position for closure proofs.
 *
 * Handles JPEG (APP1 "Exif" segment), PNG (`eXIf` chunk) and WebP (`EXIF`
 * chunk); anything else (HEIC, GIF, …) reports `present: false`. Never throws.
 */

export interface PhotoExif {
  /** The original file had an EXIF block (camera photos do; screenshots, forwards and stock images usually don't). */
  present: boolean;
  /** Decimal degrees from the EXIF GPS IFD, when the photo is geotagged. */
  lat?: number;
  lng?: number;
}

const NO_EXIF: PhotoExif = { present: false };

/** First read: camera JPEGs keep EXIF within the first few KB. */
const HEAD_BYTES = 256 * 1024;
/** Cap for the second, full read (PNG/WebP may store EXIF after the pixel data). */
const MAX_SCAN_BYTES = 32 * 1024 * 1024;

/** Returned when the bytes read so far end before an answer was reached. */
const NEED_MORE = 'need-more';
type ParseResult = PhotoExif | typeof NEED_MORE;

/** Bytes per value for each TIFF field type (1 BYTE … 12 DOUBLE, 13 IFD). */
const TYPE_SIZES: Record<number, number> = { 1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4 };

const TAG_GPS_IFD = 0x8825;
const TAG_GPS_LAT_REF = 0x0001;
const TAG_GPS_LAT = 0x0002;
const TAG_GPS_LNG_REF = 0x0003;
const TAG_GPS_LNG = 0x0004;

interface IfdEntry {
  type: number;
  count: number;
  /** Absolute byte position of the value (inline in the entry, or via its offset). */
  at: number;
}

function ascii(view: DataView, at: number, len: number): string {
  if (at < 0 || at + len > view.byteLength) return '';
  let s = '';
  for (let i = 0; i < len; i++) s += String.fromCharCode(view.getUint8(at + i));
  return s;
}

/** One IFD as tag → entry. `start`/`end` bound the TIFF block; IFD and value offsets are relative to `start`. */
function readIfd(view: DataView, start: number, end: number, offset: number, le: boolean): Map<number, IfdEntry> {
  const entries = new Map<number, IfdEntry>();
  const base = start + offset;
  if (offset < 8 || base + 2 > end) return entries;
  const n = view.getUint16(base, le);
  for (let i = 0; i < n; i++) {
    const p = base + 2 + i * 12;
    if (p + 12 > end) break;
    const type = view.getUint16(p + 2, le);
    const count = view.getUint32(p + 4, le);
    const size = (TYPE_SIZES[type] ?? 0) * count;
    const at = size <= 4 ? p + 8 : start + view.getUint32(p + 8, le);
    if (size > 0 && at + size <= end) entries.set(view.getUint16(p, le), { type, count, at });
  }
  return entries;
}

function readOffset(view: DataView, e: IfdEntry, le: boolean): number | null {
  if (e.type === 3) return view.getUint16(e.at, le);
  if (e.type === 4 || e.type === 13) return view.getUint32(e.at, le);
  return null;
}

/** Degrees from up to three (S)RATIONALs: degrees, minutes, seconds. */
function readDegrees(view: DataView, e: IfdEntry, le: boolean): number | null {
  if (e.type !== 5 && e.type !== 10) return null;
  const signed = e.type === 10;
  let deg = 0;
  for (let i = 0; i < Math.min(3, e.count); i++) {
    const p = e.at + i * 8;
    const num = signed ? view.getInt32(p, le) : view.getUint32(p, le);
    const den = signed ? view.getInt32(p + 4, le) : view.getUint32(p + 4, le);
    if (den === 0) {
      if (i > 0 && num === 0) continue; // 0/0 minutes or seconds: treat as zero
      return null; // 0/0 degrees = no fix
    }
    deg += num / den / 60 ** i;
  }
  return deg;
}

function readRef(view: DataView, e: IfdEntry | undefined): string {
  return e && e.type === 2 ? String.fromCharCode(view.getUint8(e.at)).toUpperCase() : '';
}

/** GPS position from a TIFF block (the payload of an EXIF segment or chunk). */
function tiffGps(view: DataView, start: number, end: number): Pick<PhotoExif, 'lat' | 'lng'> {
  if (start < 0 || start + 8 > end) return {};
  const order = view.getUint16(start);
  if (order !== 0x4949 && order !== 0x4d4d) return {}; // 'II' little-endian, 'MM' big-endian
  const le = order === 0x4949;
  if (view.getUint16(start + 2, le) !== 42) return {};
  const ifd0 = readIfd(view, start, end, view.getUint32(start + 4, le), le);
  const pointer = ifd0.get(TAG_GPS_IFD);
  const gpsOffset = pointer ? readOffset(view, pointer, le) : null;
  if (!gpsOffset) return {};
  const gps = readIfd(view, start, end, gpsOffset, le);
  const latEntry = gps.get(TAG_GPS_LAT);
  const lngEntry = gps.get(TAG_GPS_LNG);
  let lat = latEntry ? readDegrees(view, latEntry, le) : null;
  let lng = lngEntry ? readDegrees(view, lngEntry, le) : null;
  if (lat === null || lng === null) return {};
  if (readRef(view, gps.get(TAG_GPS_LAT_REF)) === 'S') lat = -Math.abs(lat);
  if (readRef(view, gps.get(TAG_GPS_LNG_REF)) === 'W') lng = -Math.abs(lng);
  // 0,0 is what some cameras write when they had no fix.
  if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180 || (lat === 0 && lng === 0)) return {};
  return { lat, lng };
}

/** Some writers prefix a PNG/WebP EXIF payload with the JPEG-style "Exif\0\0" header. */
function skipExifHeader(view: DataView, at: number): number {
  return ascii(view, at, 4) === 'Exif' ? at + 6 : at;
}

function parseJpeg(view: DataView, complete: boolean): ParseResult {
  const len = view.byteLength;
  let off = 2;
  while (off + 4 <= len) {
    if (view.getUint8(off) !== 0xff) return NO_EXIF; // lost sync: not a well-formed header
    const marker = view.getUint8(off + 1);
    if (marker === 0xff) {
      off += 1; // fill byte
      continue;
    }
    if (marker === 0x01 || marker === 0xd8 || (marker >= 0xd0 && marker <= 0xd7)) {
      off += 2; // standalone marker, no length
      continue;
    }
    if (marker === 0xda || marker === 0xd9) return NO_EXIF; // image data / end: metadata comes before this
    const size = view.getUint16(off + 2);
    if (size < 2) return NO_EXIF;
    const segEnd = off + 2 + size;
    if (marker === 0xe1 && ascii(view, off + 4, 4) === 'Exif' && off + 10 <= len && view.getUint8(off + 8) === 0) {
      if (segEnd > len && !complete) return NEED_MORE;
      return { present: true, ...tiffGps(view, off + 10, Math.min(segEnd, len)) };
    }
    off = segEnd;
  }
  return complete ? NO_EXIF : NEED_MORE;
}

function parsePng(view: DataView, complete: boolean): ParseResult {
  const len = view.byteLength;
  let off = 8;
  while (off + 8 <= len) {
    const size = view.getUint32(off);
    const type = ascii(view, off + 4, 4);
    const data = off + 8;
    if (type === 'eXIf') {
      if (data + size > len && !complete) return NEED_MORE;
      return { present: true, ...tiffGps(view, skipExifHeader(view, data), Math.min(data + size, len)) };
    }
    if (type === 'IEND') return NO_EXIF;
    off = data + size + 4; // + CRC
  }
  return complete ? NO_EXIF : NEED_MORE;
}

function parseWebp(view: DataView, complete: boolean): ParseResult {
  const len = view.byteLength;
  let off = 12;
  while (off + 8 <= len) {
    const fourcc = ascii(view, off, 4);
    const size = view.getUint32(off + 4, true);
    const data = off + 8;
    if (fourcc === 'EXIF') {
      if (data + size > len && !complete) return NEED_MORE;
      return { present: true, ...tiffGps(view, skipExifHeader(view, data), Math.min(data + size, len)) };
    }
    // Simple (VP8 / VP8L) files have no metadata; extended ones announce EXIF in the VP8X flags.
    if (off === 12 && (fourcc === 'VP8 ' || fourcc === 'VP8L')) return NO_EXIF;
    if (fourcc === 'VP8X' && data < len && (view.getUint8(data) & 0x08) === 0) return NO_EXIF;
    off = data + size + (size & 1); // chunks are padded to an even size
  }
  return complete ? NO_EXIF : NEED_MORE;
}

function parse(buf: ArrayBuffer, complete: boolean): ParseResult {
  const view = new DataView(buf);
  if (view.byteLength < 12) return NO_EXIF;
  if (view.getUint16(0) === 0xffd8) return parseJpeg(view, complete);
  if (view.getUint32(0) === 0x89504e47 && view.getUint32(4) === 0x0d0a1a0a) return parsePng(view, complete);
  if (ascii(view, 0, 4) === 'RIFF' && ascii(view, 8, 4) === 'WEBP') return parseWebp(view, complete);
  return NO_EXIF;
}

function readBytes(file: Blob, n: number): Promise<ArrayBuffer> {
  const part = file.slice(0, n);
  if (typeof part.arrayBuffer === 'function') return part.arrayBuffer();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error ?? new Error('Could not read the photo.'));
    reader.readAsArrayBuffer(part);
  });
}

/** EXIF presence and GPS of an original photo file. Never throws; unreadable files report `present: false`. */
export async function readPhotoExif(file: Blob): Promise<PhotoExif> {
  try {
    const head = parse(await readBytes(file, HEAD_BYTES), file.size <= HEAD_BYTES);
    if (head !== NEED_MORE) return head;
    const n = Math.min(file.size, MAX_SCAN_BYTES);
    const full = parse(await readBytes(file, n), n >= file.size);
    return full === NEED_MORE ? NO_EXIF : full;
  } catch {
    return NO_EXIF;
  }
}

/** The optional `photo_exif` / `photo_lat` / `photo_lng` API inputs for a photo's EXIF; empty without one. */
export function exifFields(exif: PhotoExif | null | undefined): { photo_exif?: boolean; photo_lat?: number; photo_lng?: number } {
  if (!exif) return {};
  return { photo_exif: exif.present, photo_lat: exif.lat, photo_lng: exif.lng };
}
