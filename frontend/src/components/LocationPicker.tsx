import { useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import { CircleMarker, MapContainer, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import type { DemoLocation, Ward } from '../api';
import { BENGALURU_CENTER, BENGALURU_ZOOM, fmtDistance, getPosition, isValidLatLng, nearestWard } from '../lib/geo';
import { Icon } from './Icon';
import { Spinner } from './ui';

export interface LatLng {
  lat: number;
  lng: number;
}

interface Props {
  value: LatLng | null;
  accuracy: number | null;
  source: 'gps' | 'preset' | 'manual' | null;
  onChange: (loc: LatLng, accuracy: number | null, source: 'gps' | 'preset' | 'manual') => void;
  wards: Ward[];
  presets: DemoLocation[];
  disabled?: boolean;
}

const OSM_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

function ClickToPick({ onPick, disabled, skipRecenter }: { onPick: (ll: LatLng) => void; disabled: boolean; skipRecenter: MutableRefObject<boolean> }) {
  useMapEvents({
    click(e) {
      if (disabled) return;
      skipRecenter.current = true; // the user tapped here — don't yank the map around
      onPick({ lat: e.latlng.lat, lng: e.latlng.lng });
    },
  });
  return null;
}

function Recenter({ value, skipRecenter }: { value: LatLng | null; skipRecenter: MutableRefObject<boolean> }) {
  const map = useMap();
  useEffect(() => {
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(map.getContainer());
    return () => ro.disconnect();
  }, [map]);
  useEffect(() => {
    if (!value) return;
    if (skipRecenter.current) {
      skipRecenter.current = false;
      return;
    }
    map.setView([value.lat, value.lng], Math.max(map.getZoom(), 15), { animate: true });
  }, [map, value, skipRecenter]);
  return null;
}

export function LocationPicker({ value, accuracy, source, onChange, wards, presets, disabled = false }: Props) {
  const [latText, setLatText] = useState(value ? value.lat.toFixed(5) : '');
  const [lngText, setLngText] = useState(value ? value.lng.toFixed(5) : '');
  const [locating, setLocating] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);
  const skipRecenter = useRef(false);

  // Keep the text inputs in sync with external changes (GPS / preset / map click).
  useEffect(() => {
    if (!value) return;
    setLatText((t) => (Number(t) === value.lat ? t : value.lat.toFixed(5)));
    setLngText((t) => (Number(t) === value.lng ? t : value.lng.toFixed(5)));
  }, [value]);

  const near = useMemo(() => (value && wards.length ? nearestWard(wards, value.lat, value.lng) : null), [value, wards]);
  const presetIndex = useMemo(() => (value ? presets.findIndex((p) => Math.abs(p.lat - value.lat) < 1e-6 && Math.abs(p.lng - value.lng) < 1e-6) : -1), [presets, value]);

  async function useMyLocation() {
    setGeoError(null);
    setLocating(true);
    try {
      const pos = await getPosition(12_000);
      onChange({ lat: pos.coords.latitude, lng: pos.coords.longitude }, pos.coords.accuracy ?? null, 'gps');
    } catch (e) {
      setGeoError(e instanceof Error ? e.message : 'Could not get your location.');
    } finally {
      setLocating(false);
    }
  }

  function commitManual(latS: string, lngS: string) {
    const lat = Number(latS);
    const lng = Number(lngS);
    if (latS.trim() === '' || lngS.trim() === '' || !isValidLatLng(lat, lng)) return;
    if (value && Math.abs(value.lat - lat) < 1e-9 && Math.abs(value.lng - lng) < 1e-9) return;
    onChange({ lat, lng }, null, 'manual');
  }

  return (
    <div className="location-picker">
      <div className="loc-controls">
        <button type="button" className="btn btn-secondary" onClick={() => void useMyLocation()} disabled={disabled || locating}>
          {locating ? <Spinner size={16} /> : <Icon name="navigation" size={16} />} Use my location
        </button>
        <label className="field-inline grow">
          <span className="sr-only">Demo location preset</span>
          <select
            className="select"
            value={presetIndex >= 0 ? String(presetIndex) : ''}
            disabled={disabled}
            onChange={(e) => {
              const p = presets[Number(e.target.value)];
              if (p) onChange({ lat: p.lat, lng: p.lng }, null, 'preset');
            }}
          >
            <option value="">Demo presets…</option>
            {presets.map((p, i) => (
              <option key={p.name} value={String(i)}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="loc-map">
        <MapContainer center={value ? [value.lat, value.lng] : BENGALURU_CENTER} zoom={value ? 15 : BENGALURU_ZOOM} className="map map-mini" scrollWheelZoom={false} aria-label="Pick the spot on the map">
          <TileLayer attribution={OSM_ATTR} url={OSM_URL} maxZoom={19} />
          <ClickToPick onPick={(ll) => onChange(ll, null, 'manual')} disabled={disabled} skipRecenter={skipRecenter} />
          <Recenter value={value} skipRecenter={skipRecenter} />
          {value ? (
            <>
              {accuracy && accuracy > 15 ? <CircleMarker center={[value.lat, value.lng]} radius={Math.min(60, Math.max(14, accuracy / 4))} interactive={false} pathOptions={{ color: '#4f46e5', weight: 1, fillColor: '#4f46e5', fillOpacity: 0.12 }} /> : null}
              <CircleMarker center={[value.lat, value.lng]} radius={9} pathOptions={{ color: '#ffffff', weight: 3, fillColor: '#4f46e5', fillOpacity: 1 }} />
            </>
          ) : null}
        </MapContainer>
        <div className="loc-map-hint">Tap the map to adjust the pin</div>
      </div>

      <div className="loc-coords">
        <label className="field">
          <span className="field-label">Latitude</span>
          <input
            className="input"
            inputMode="decimal"
            value={latText}
            disabled={disabled}
            onChange={(e) => {
              setLatText(e.target.value);
              commitManual(e.target.value, lngText);
            }}
            aria-invalid={latText !== '' && !Number.isFinite(Number(latText))}
          />
        </label>
        <label className="field">
          <span className="field-label">Longitude</span>
          <input
            className="input"
            inputMode="decimal"
            value={lngText}
            disabled={disabled}
            onChange={(e) => {
              setLngText(e.target.value);
              commitManual(latText, e.target.value);
            }}
            aria-invalid={lngText !== '' && !Number.isFinite(Number(lngText))}
          />
        </label>
      </div>

      <div className="loc-summary">
        {value ? (
          <>
            <span className="chip chip-info chip-wrap">
              <Icon name="pin" size={13} />
              <span>
                {near ? (
                  <>
                    Nearest ward: <strong>{near.ward.name}</strong> ({near.ward.zone}) · {fmtDistance(near.distance_m)} from centroid
                  </>
                ) : (
                  'Ward lookup pending…'
                )}
              </span>
            </span>
            {source === 'gps' ? (
              <span className={`chip ${accuracy && accuracy > 100 ? 'chip-warn' : 'chip-ok'}`}>
                <Icon name="navigation" size={13} /> GPS{accuracy ? ` ±${Math.round(accuracy)} m` : ''}
              </span>
            ) : source === 'preset' ? (
              <span className="chip chip-muted">Demo preset</span>
            ) : (
              <span className="chip chip-muted">Manual</span>
            )}
          </>
        ) : (
          <span className="muted">No location yet — use GPS, pick a preset or tap the map.</span>
        )}
      </div>
      {geoError ? (
        <p className="field-error" role="alert">
          {geoError}
        </p>
      ) : null}
    </div>
  );
}
