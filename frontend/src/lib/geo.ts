import type { Ward } from '../api';
import { getLang, translate } from '../i18n';

export const BENGALURU_CENTER: [number, number] = [12.9716, 77.5946];
export const BENGALURU_ZOOM = 12;

const EARTH_RADIUS_M = 6_371_000;

/** Great-circle distance in metres (same formula as backend/app/geo.py). */
export function haversineM(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const p1 = toRad(lat1);
  const p2 = toRad(lat2);
  const dp = p2 - p1;
  const dl = toRad(lng2 - lng1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a));
}

export interface NearestWard {
  ward: Ward;
  distance_m: number;
}

export function nearestWard(wards: Ward[], lat: number, lng: number): NearestWard | null {
  let best: NearestWard | null = null;
  for (const w of wards) {
    const d = haversineM(lat, lng, w.lat, w.lng);
    if (!best || d < best.distance_m) best = { ward: w, distance_m: d };
  }
  return best;
}

export function fmtDistance(m: number): string {
  if (m < 1000) return `${Math.round(m)} m`;
  return `${(m / 1000).toFixed(1)} km`;
}

export function isValidLatLng(lat: number, lng: number): boolean {
  return Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180;
}

function geoErrorMessage(err: GeolocationPositionError): string {
  const lang = getLang();
  switch (err.code) {
    case err.PERMISSION_DENIED:
      return translate(lang, 'geo.denied');
    case err.POSITION_UNAVAILABLE:
      return translate(lang, 'geo.unavailable');
    case err.TIMEOUT:
      return translate(lang, 'geo.timeout');
    default:
      return lang === 'en' && err.message ? err.message : translate(lang, 'location.error');
  }
}

export function getPosition(timeoutMs = 10_000): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (typeof navigator === 'undefined' || !('geolocation' in navigator)) {
      reject(new Error(translate(getLang(), 'geo.unsupported')));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, (err) => reject(new Error(geoErrorMessage(err))), {
      enableHighAccuracy: true,
      timeout: timeoutMs,
      maximumAge: 30_000,
    });
  });
}

/**
 * `getPosition` that resolves null instead of rejecting. Adds a hard deadline:
 * the browser's own timeout does not count time spent on the permission prompt.
 */
export function tryGetPosition(timeoutMs = 6000): Promise<GeolocationPosition | null> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => resolve(null), timeoutMs + 1500);
    getPosition(timeoutMs).then(
      (pos) => {
        window.clearTimeout(timer);
        resolve(pos);
      },
      () => {
        window.clearTimeout(timer);
        resolve(null);
      },
    );
  });
}

/** Phones and tablets (coarse pointer), where the browser position is usually real GPS. */
export function isTouchDevice(): boolean {
  try {
    return typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches;
  } catch {
    return false;
  }
}

/** Worst device accuracy (m) still sent as a proof photo's capture location. */
export const PROOF_MAX_ACCURACY_M = 100;

/**
 * Device position to send with a closure/verification photo, or null. Only touch
 * devices with a fix of ≤ 100 m qualify: desktop browsers report Wi-Fi/IP guesses
 * that would get a demo flagged as the wrong spot. The photo's own EXIF GPS still
 * wins on the server. Never rejects.
 */
export async function proofPosition(timeoutMs = 6000): Promise<{ lat: number; lng: number; accuracy: number } | null> {
  if (!isTouchDevice()) return null;
  const pos = await tryGetPosition(timeoutMs);
  if (!pos || !(pos.coords.accuracy <= PROOF_MAX_ACCURACY_M)) return null;
  return { lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy };
}
