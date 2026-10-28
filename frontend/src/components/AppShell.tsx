import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { api, errorMessage, type Health, type Notification as InboxNotification } from '../api';
import { useApp } from '../context/AppContext';
import { useI18n } from '../i18n';
import { LanguageToggle } from '../i18n/LanguageToggle';
import { Icon, LogoMark } from './Icon';
import { useToast } from './Toast';

function AiPill({ health, error }: { health: Health | null; error: string | null }) {
  const { t } = useI18n();
  if (error && !health) {
    return (
      <span className="pill pill-bad" title={error}>
        <span className="pill-dot" /> {t('shell.ai.offline')}
      </span>
    );
  }
  if (!health) {
    return (
      <span className="pill pill-muted">
        <span className="pill-dot" /> {t('shell.ai.connecting')}
      </span>
    );
  }
  if (health.ai_mode === 'gemini') {
    const title = t('shell.ai.modelTitle', { model: health.model ?? t('common.unknown') });
    return (
      <span className="pill pill-good" title={health.last_ai_error ? `${title}\n${t('shell.ai.lastError', { error: health.last_ai_error })}` : title}>
        <span className="pill-dot" /> {t('shell.ai.gemini')}
      </span>
    );
  }
  return (
    <span className="pill pill-warn" title={t('shell.ai.heuristicTitle')}>
      <span className="pill-dot" />
      <span className="pill-long">{t('shell.ai.heuristicLong')}</span>
      <span className="pill-short">{t('shell.ai.heuristicShort')}</span>
    </span>
  );
}

/** Close a `<details>` dropdown on outside click / Escape. */
function useDismissableMenu(ref: RefObject<HTMLDetailsElement | null>) {
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      const el = ref.current;
      if (el?.open && e.target instanceof Node && !el.contains(e.target)) el.open = false;
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && ref.current) ref.current.open = false;
    }
    document.addEventListener('click', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [ref]);
}

/** Header bell: proof-photo requests addressed to this browser's reporter id (CUJ-3). */
function NotificationInbox() {
  const { reporterId, dataVersion } = useApp();
  const { t, label: vocab, fmt } = useI18n();
  const toast = useToast();
  const navigate = useNavigate();
  const ref = useRef<HTMLDetailsElement>(null);
  // Bumped by every load and mutation so a slow poll can't resurrect items just marked read.
  const seqRef = useRef(0);
  const [items, setItems] = useState<InboxNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [busy, setBusy] = useState(false);

  useDismissableMenu(ref);

  const load = useCallback(async () => {
    const seq = ++seqRef.current;
    try {
      const res = await api.notifications(reporterId);
      if (seq !== seqRef.current) return;
      setItems(res.notifications);
      setUnread(res.unread);
    } catch {
      /* best-effort: the AI pill already shows when the API is unreachable */
    }
  }, [reporterId]);

  // Poll every 30 s, and straight away whenever data changes (seed/reset, a closure).
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(timer);
  }, [load, dataVersion]);

  async function openItem(n: InboxNotification) {
    if (ref.current) ref.current.open = false;
    seqRef.current++;
    setItems((list) => list.filter((x) => x.id !== n.id));
    setUnread((u) => Math.max(0, u - 1));
    navigate(`/clusters/${n.cluster_id}`);
    try {
      const res = await api.markNotificationsRead(reporterId, [n.id]);
      setUnread(res.unread);
    } catch {
      /* the next poll reconciles */
    }
  }

  async function markAllRead() {
    seqRef.current++;
    setBusy(true);
    try {
      const res = await api.markNotificationsRead(reporterId);
      setItems([]);
      setUnread(res.unread);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const label = unread ? t('inbox.labelUnread', { count: unread }) : t('inbox.title');

  return (
    <details
      className="menu inbox"
      ref={ref}
      onToggle={(e) => {
        if (e.currentTarget.open) void load();
      }}
    >
      <summary className="btn btn-ghost btn-sm menu-summary inbox-summary" aria-label={label} title={label}>
        <Icon name="bell" size={16} />
        {unread > 0 ? (
          <span className="inbox-badge" aria-hidden="true">
            {unread > 9 ? '9+' : unread}
          </span>
        ) : null}
      </summary>
      <div className="menu-list inbox-list">
        <div className="inbox-head">
          <strong>{t('inbox.title')}</strong>
          {items.length > 0 ? (
            <button type="button" className="inbox-mark" onClick={() => void markAllRead()} disabled={busy}>
              {t('inbox.markAllRead')}
            </button>
          ) : null}
        </div>
        {items.length === 0 ? (
          <p className="inbox-empty muted small">{t('inbox.empty')}</p>
        ) : (
          <ul className="inbox-items">
            {items.map((n) => (
              <li key={n.id}>
                <button type="button" className="inbox-item" onClick={() => void openItem(n)}>
                  <Icon name={n.kind === 'verification_request' ? 'camera' : 'bell'} size={15} />
                  <strong>{n.cluster?.title || n.cluster_id}</strong>
                  <span className="inbox-msg">{n.message}</span>
                  <small>
                    <time dateTime={n.created_at}>{fmt.timeAgo(n.created_at)}</time>
                    {n.cluster?.ward ? ` · ${vocab('ward', n.cluster.ward, n.cluster.ward)}` : ''}
                  </small>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}

export default function AppShell() {
  const { health, healthError, officialMode, setOfficialMode, bumpData, refreshHealth } = useApp();
  const { t } = useI18n();
  const toast = useToast();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<'seed' | 'reset' | null>(null);
  const menuRef = useRef<HTMLDetailsElement>(null);

  // Close the demo menu on outside click / Escape.
  useDismissableMenu(menuRef);

  async function runDemo(action: 'seed' | 'reset') {
    if (menuRef.current) menuRef.current.open = false;
    if (action === 'reset' && !window.confirm(t('demo.confirmReset'))) return;
    setBusy(action);
    try {
      if (action === 'seed') {
        const s = await api.seed(true);
        toast.success(t('demo.seeded', { count: s.clusters }));
      } else {
        await api.reset();
        toast.info(t('demo.wiped'));
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
        {t('shell.skip')}
      </a>
      <header className="header">
        <div className="header-inner">
          <Link to="/" className="brand" aria-label={t('shell.home')}>
            <LogoMark size={34} />
            <span className="brand-text">
              <strong>CivicPulse</strong>
              <small>{t('app.tagline')}</small>
            </span>
          </Link>

          <nav className="nav" aria-label={t('nav.primary')}>
            <NavLink to="/" end>
              <Icon name="map" size={16} /> {t('nav.map')}
            </NavLink>
            <NavLink to="/report">
              <Icon name="plus-circle" size={16} /> {t('nav.report')}
            </NavLink>
            <NavLink to="/scorecard">
              <Icon name="bar-chart" size={16} /> {t('nav.scorecard')}
            </NavLink>
          </nav>

          <div className="header-tools">
            <LanguageToggle />
            <NotificationInbox />
            <AiPill health={health} error={healthError} />

            <button
              type="button"
              role="switch"
              aria-checked={officialMode}
              className={`switch${officialMode ? ' on' : ''}`}
              onClick={() => setOfficialMode(!officialMode)}
              title={t('shell.official.title')}
            >
              <span className="switch-track" aria-hidden="true">
                <span className="switch-thumb" />
              </span>
              <span className="switch-label">{t('shell.official.label')}</span>
            </button>

            {health?.demo_mode !== false ? (
              <details className="menu" ref={menuRef}>
                <summary className="btn btn-ghost btn-sm menu-summary" aria-label={t('demo.menu')}>
                  {busy ? <span className="spinner" style={{ width: 14, height: 14 }} /> : <Icon name="zap" size={14} />}
                  <span className="menu-summary-text">{t('demo.label')}</span>
                </summary>
                <div className="menu-list" role="menu">
                  <button type="button" role="menuitem" onClick={() => void runDemo('seed')} disabled={busy !== null}>
                    <Icon name="spark" size={15} /> {t('demo.seed')}
                    <small>{t('demo.seedHint')}</small>
                  </button>
                  <button type="button" role="menuitem" className="danger" onClick={() => void runDemo('reset')} disabled={busy !== null}>
                    <Icon name="trash" size={15} /> {t('demo.reset')}
                    <small>{t('demo.resetHint')}</small>
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
            <strong>{t('shell.official.stripTitle')}</strong> {t('shell.official.stripBody')}
          </span>
        </div>
      ) : null}

      <main id="main" className="main">
        <Outlet />
      </main>

      <nav className="tabbar" aria-label={t('nav.primaryMobile')}>
        <NavLink to="/" end>
          <Icon name="map" size={20} />
          <span>{t('nav.map')}</span>
        </NavLink>
        <NavLink to="/report" className="tab-report">
          <span className="tab-report-btn">
            <Icon name="plus-circle" size={22} />
          </span>
          <span>{t('nav.report')}</span>
        </NavLink>
        <NavLink to="/scorecard">
          <Icon name="bar-chart" size={20} />
          <span>{t('nav.scorecard')}</span>
        </NavLink>
      </nav>
    </div>
  );
}
