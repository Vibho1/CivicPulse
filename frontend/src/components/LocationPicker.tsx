import { useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import { CircleMarker, MapContainer, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import type { DemoLocation, Ward } from '../api';
import { useI18n } from '../i18n';
import { BENGALURU_CENTER, BENGALURU_ZOOM, getPosition, isValidLatLng, nearestWard } from '../lib/geo';
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
  const { t, tx, fmt, label } = useI18n();
  const [latText, setLatText] = useState(value ? value.lat.toFixed(5) : '');
  const [lngText, setLngText] = useState(value ? value.lng.toFixed(5) : '');
  const [locating, setLocating] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);
  const skipRecenter = useRef(false);

  // Keep the text inputs in sync with external changes (GPS / preset / map click).
  useEffect(() => {
    if (!value) return;
    setLatText((s) => (Number(s) === value.lat ? s : value.lat.toFixed(5)));
    setLngText((s) => (Number(s) === value.lng ? s : value.lng.toFixed(5)));
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
      // lib/geo already words its errors in the active language.
      setGeoError(e instanceof Error ? e.message : t('location.error'));
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
          {locating ? <Spinner size={16} /> : <Icon name="navigation" size={16} />} {t('location.useMine')}
        </button>
        <label className="field-inline grow">
          <span className="sr-only">{t('location.presetLabel')}</span>
          <select
            className="select"
            value={presetIndex >= 0 ? String(presetIndex) : ''}
            disabled={disabled}
            onChange={(e) => {
              const p = presets[Number(e.target.value)];
              if (p) onChange({ lat: p.lat, lng: p.lng }, null, 'preset');
            }}
          >
            <option value="">{t('location.presetPlaceholder')}</option>
            {presets.map((p, i) => (
              <option key={p.name} value={String(i)}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="loc-map">
        <MapContainer center={value ? [value.lat, value.lng] : BENGALURU_CENTER} zoom={value ? 15 : BENGALURU_ZOOM} className="map map-mini" scrollWheelZoom={false} aria-label={t('location.mapLabel')}>
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
        <div className="loc-map-hint">{t('location.mapHint')}</div>
      </div>

      <div className="loc-coords">
        <label className="field">
          <span className="field-label">{t('location.lat')}</span>
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
          <span className="field-label">{t('location.lng')}</span>
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
                {near
                  ? tx('location.nearestWard', {
                      ward: <strong>{fmt.ward(near.ward.name, near.ward.number)}</strong>,
                      zone: label('zone', near.ward.zone, near.ward.zone),
                      distance: fmt.distance(near.distance_m),
                    })
                  : t('location.wardPending')}
              </span>
            </span>
            {source === 'gps' ? (
              <span className={`chip ${accuracy && accuracy > 100 ? 'chip-warn' : 'chip-ok'}`}>
                <Icon name="navigation" size={13} /> {accuracy ? t('location.gpsAccuracy', { accuracy: fmt.distance(accuracy) }) : t('location.gps')}
              </span>
            ) : source === 'preset' ? (
              <span className="chip chip-muted">{t('location.sourcePreset')}</span>
            ) : (
              <span className="chip chip-muted">{t('location.sourceManual')}</span>
            )}
          </>
        ) : (
          <span className="muted">{t('location.none')}</span>
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
