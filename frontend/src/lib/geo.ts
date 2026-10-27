import type { Ward } from '../api';

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
  switch (err.code) {
    case err.PERMISSION_DENIED:
      return 'Location permission denied. Pick a preset or tap the map instead.';
    case err.POSITION_UNAVAILABLE:
      return 'Location unavailable right now. Pick a preset or tap the map instead.';
    case err.TIMEOUT:
      return 'Timed out waiting for GPS. Pick a preset or tap the map instead.';
    default:
      return err.message || 'Could not get your location.';
  }
}

export function getPosition(timeoutMs = 10_000): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (typeof navigator === 'undefined' || !('geolocation' in navigator)) {
      reject(new Error('Geolocation is not available in this browser.'));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, (err) => reject(new Error(geoErrorMessage(err))), {
      enableHighAccuracy: true,
      timeout: timeoutMs,
      maximumAge: 30_000,
    });
  });
}
