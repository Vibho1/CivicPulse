import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, errorMessage, type Health, type Meta } from '../api';
import { getOfficialMode, getReporterId, setOfficialMode as persistOfficialMode } from '../lib/storage';

export interface AppContextValue {
  meta: Meta | null;
  health: Health | null;
  healthError: string | null;
  officialMode: boolean;
  setOfficialMode: (on: boolean) => void;
  reporterId: string;
  refreshHealth: () => Promise<void>;
  /** Bumped after seed/reset so every page refetches. */
  dataVersion: number;
  bumpData: () => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [officialMode, setOfficialState] = useState<boolean>(() => getOfficialMode());
  const [dataVersion, setDataVersion] = useState(0);
  const reporterId = useMemo(() => getReporterId(), []);

  const refreshHealth = useCallback(async () => {
    try {
      const h = await api.health();
      setHealth(h);
      setHealthError(null);
    } catch (e) {
      setHealthError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
    const timer = window.setInterval(() => void refreshHealth(), 60_000);
    return () => window.clearInterval(timer);
  }, [refreshHealth]);

  // Vocabulary is static; fetch once, retry whenever the API comes (back) up.
  useEffect(() => {
    if (meta) return;
    let alive = true;
    api
      .meta()
      .then((m) => {
        if (alive) setMeta(m);
      })
      .catch(() => {
        /* AI pill already shows the API is unreachable */
      });
    return () => {
      alive = false;
    };
  }, [meta, dataVersion, healthError]);

  const setOfficialMode = useCallback((on: boolean) => {
    setOfficialState(on);
    persistOfficialMode(on);
  }, []);

  const bumpData = useCallback(() => setDataVersion((v) => v + 1), []);

  const value = useMemo<AppContextValue>(
    () => ({ meta, health, healthError, officialMode, setOfficialMode, reporterId, refreshHealth, dataVersion, bumpData }),
    [meta, health, healthError, officialMode, setOfficialMode, reporterId, refreshHealth, dataVersion, bumpData],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used inside <AppProvider>');
  return ctx;
}
