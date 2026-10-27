import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { api, errorMessage, type Health } from '../api';
import { useApp } from '../context/AppContext';
import { Icon, LogoMark } from './Icon';
import { useToast } from './Toast';

function AiPill({ health, error }: { health: Health | null; error: string | null }) {
  if (error && !health) {
    return (
      <span className="pill pill-bad" title={error}>
        <span className="pill-dot" /> API offline
      </span>
    );
  }
  if (!health) {
    return (
      <span className="pill pill-muted">
        <span className="pill-dot" /> Connecting…
      </span>
    );
  }
  if (health.ai_mode === 'gemini') {
    return (
      <span className="pill pill-good" title={`Gemini model: ${health.model ?? 'unknown'}${health.last_ai_error ? `\nLast error: ${health.last_ai_error}` : ''}`}>
        <span className="pill-dot" /> Gemini live
      </span>
    );
  }
  return (
    <span className="pill pill-warn" title="The backend is running without GEMINI_API_KEY: no transcription or vision, rule-based routing only.">
      <span className="pill-dot" />
      <span className="pill-long">Offline heuristic — set GEMINI_API_KEY</span>
      <span className="pill-short">Offline heuristic</span>
    </span>
  );
}

export default function AppShell() {
  const { health, healthError, officialMode, setOfficialMode, bumpData, refreshHealth } = useApp();
  const toast = useToast();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<'seed' | 'reset' | null>(null);
  const menuRef = useRef<HTMLDetailsElement>(null);

  // Close the demo menu on outside click / Escape.
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      const el = menuRef.current;
      if (el?.open && e.target instanceof Node && !el.contains(e.target)) el.open = false;
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && menuRef.current) menuRef.current.open = false;
    }
    document.addEventListener('click', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, []);

  async function runDemo(action: 'seed' | 'reset') {
    if (menuRef.current) menuRef.current.open = false;
    if (action === 'reset' && !window.confirm('Wipe all issues, reports and photos?')) return;
    setBusy(action);
    try {
      if (action === 'seed') {
        const s = await api.seed(true);
        toast.success(`Seeded ${s.clusters} demo issues across Bengaluru.`);
      } else {
        await api.reset();
        toast.info('All data wiped. Seed demo data or file a report to start again.');
      }
      bumpData();
      void refreshHealth();
      navigate('/');
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={`app${officialMode ? ' official' : ''}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="header">
        <div className="header-inner">
          <Link to="/" className="brand" aria-label="CivicPulse home">
            <LogoMark size={34} />
            <span className="brand-text">
              <strong>CivicPulse</strong>
              <small>From complaint to closure, with proof</small>
            </span>
          </Link>

          <nav className="nav" aria-label="Primary">
            <NavLink to="/" end>
              <Icon name="map" size={16} /> Map
            </NavLink>
            <NavLink to="/report">
              <Icon name="plus-circle" size={16} /> Report
            </NavLink>
            <NavLink to="/scorecard">
              <Icon name="bar-chart" size={16} /> Scorecard
            </NavLink>
          </nav>

          <div className="header-tools">
            <AiPill health={health} error={healthError} />

            <button
              type="button"
              role="switch"
              aria-checked={officialMode}
              className={`switch${officialMode ? ' on' : ''}`}
              onClick={() => setOfficialMode(!officialMode)}
              title="Official mode reveals status and closure actions (demo: no login)"
            >
              <span className="switch-track" aria-hidden="true">
                <span className="switch-thumb" />
              </span>
              <span className="switch-label">Official mode</span>
            </button>

            {health?.demo_mode !== false ? (
              <details className="menu" ref={menuRef}>
                <summary className="btn btn-ghost btn-sm menu-summary" aria-label="Demo menu">
                  {busy ? <span className="spinner" style={{ width: 14, height: 14 }} /> : <Icon name="zap" size={14} />}
                  <span className="menu-summary-text">Demo</span>
                </summary>
                <div className="menu-list" role="menu">
                  <button type="button" role="menuitem" onClick={() => void runDemo('seed')} disabled={busy !== null}>
                    <Icon name="spark" size={15} /> Seed demo data
                    <small>Loads the Bengaluru story: fake closure, cosmetic fix, repeat failure…</small>
                  </button>
                  <button type="button" role="menuitem" className="danger" onClick={() => void runDemo('reset')} disabled={busy !== null}>
                    <Icon name="trash" size={15} /> Reset
                    <small>Wipes everything</small>
                  </button>
                </div>
              </details>
            ) : null}
          </div>
        </div>
      </header>

      {officialMode ? (
        <div className="official-strip" role="note">
          <Icon name="shield" size={14} />
          <span>
            <strong>Official mode.</strong> You can change status and mark issues resolved. Every closure is AI-checked against the citizen's before-photo and shown
            publicly.
          </span>
        </div>
      ) : null}

      <main id="main" className="main">
        <Outlet />
      </main>

      <nav className="tabbar" aria-label="Primary (mobile)">
        <NavLink to="/" end>
          <Icon name="map" size={20} />
          <span>Map</span>
        </NavLink>
        <NavLink to="/report" className="tab-report">
          <span className="tab-report-btn">
            <Icon name="plus-circle" size={22} />
          </span>
          <span>Report</span>
        </NavLink>
        <NavLink to="/scorecard">
          <Icon name="bar-chart" size={20} />
          <span>Scorecard</span>
        </NavLink>
      </nav>
    </div>
  );
}
