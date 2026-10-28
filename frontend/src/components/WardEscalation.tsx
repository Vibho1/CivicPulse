import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, errorCode, errorMessage, type EscalationPackage, type WardRow } from '../api';
import { useI18n } from '../i18n';
import { agencyCode } from '../lib/status';
import { getRequesterName, setRequesterName } from '../lib/storage';
import { useDebounced } from '../lib/useDebounced';
import { EscalationDraftViewer, downloadPackage, packageDrafts } from './ActionPanels';
import { Icon } from './Icon';
import { AgencyCodeChip, Spinner, StatusBadge } from './ui';

/**
 * Modal with a ward-level escalation package: the ward's Unverified closures and
 * SLA-breached open issues bundled into one email, X post and RTI request.
 */
export function WardEscalationDialog({ ward, onClose }: { ward: WardRow; onClose: () => void }) {
  const { lang, t, fmt, label } = useI18n();
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [name, setName] = useState(() => getRequesterName());
  const requester = useDebounced(name.trim(), 600);
  const [pkg, setPkg] = useState<EscalationPackage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** 409 `nothing_to_escalate`: the server's explanation. */
  const [nothing, setNothing] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  // Open as a modal (focus trap, Esc to close, backdrop); fall back to a plain open dialog.
  useEffect(() => {
    const d = ref.current;
    if (!d || d.open) return;
    if (typeof d.showModal === 'function') d.showModal();
    else d.setAttribute('open', '');
  }, []);

  useEffect(() => setRequesterName(name), [name]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    api
      .wardEscalationPackage(ward.ward, { requester_name: requester || undefined })
      .then((p) => {
        if (!alive) return;
        setPkg(p);
        setNothing(null);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        if (errorCode(e) === 'nothing_to_escalate') {
          setPkg(null);
          setNothing(errorMessage(e));
        } else {
          setError(errorMessage(e));
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [ward.ward, requester, attempt]);

  /** Closing fires the dialog's `close` event, which tells the parent to unmount us. */
  const close = () => {
    const d = ref.current;
    if (d?.open && typeof d.close === 'function') d.close();
    else onClose();
  };

  const pending = name.trim() !== requester; // waiting for the debounce
  const title = fmt.ward(ward.ward, pkg?.ward_number ?? ward.number);

  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) close(); // backdrop click
      }}
    >
      <div className="panel">
        <div className="panel-head">
          <h3 id={titleId}>
            <Icon name="send" size={16} /> {t('escalate.wardHeading', { ward: title })}
          </h3>
          <button type="button" className="icon-btn" onClick={close} aria-label={t('common.close')}>
            <Icon name="x" size={16} />
          </button>
        </div>
        <p className="muted small">{t('escalate.wardIntro')}</p>

        <label className="field">
          <span className="field-label">{t('escalate.name')}</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={t('escalate.namePlaceholder')} maxLength={80} autoComplete="name" />
        </label>

        {nothing ? (
          <div className="banner banner-info" role="status">
            <Icon name="info" size={18} />
            <div>{lang === 'en' ? nothing : t('escalate.nothing', { ward: title })}</div>
          </div>
        ) : !pkg ? (
          error ? (
            <div className="banner banner-bad" role="alert">
              <Icon name="alert" size={18} />
              <div>
                {error}{' '}
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAttempt((n) => n + 1)}>
                  <Icon name="refresh" size={14} /> {t('common.retry')}
                </button>
              </div>
            </div>
          ) : (
            <Spinner label={t('escalate.preparingWard')} />
          )
        ) : (
          <>
            <div className="pkg-summary">
              <strong>{pkg.title}</strong>
              <span className="muted small"> · {fmt.count('issue', pkg.clusters.length)}</span>
            </div>
            <ul className="pkg-clusters" aria-label={t('escalate.issuesInPackage')}>
              {pkg.clusters.map((c) => (
                <li key={c.id} className="pkg-cluster">
                  <div className="pkg-cluster-head">
                    <Link to={`/clusters/${c.id}`} className="pkg-cluster-id" onClick={close}>
                      {c.id}
                    </Link>
                    <StatusBadge status={c.status} size="sm" />
                    {c.sla_breached ? (
                      <span className="chip chip-bad">
                        <Icon name="clock" size={12} /> {t('sla.breached')}
                      </span>
                    ) : null}
                  </div>
                  <div className="pkg-cluster-title">{c.title}</div>
                  <div className="chips">
                    <span className="chip chip-agency">
                      <Icon name="shield" size={12} /> {label('agencyName', c.agency, c.agency_label)}
                    </span>
                    <AgencyCodeChip code={agencyCode(c.agency, c.agency_code)} />
                  </div>
                  {c.failure_reason ? <p className="muted small">{c.failure_reason}</p> : null}
                </li>
              ))}
            </ul>
            <EscalationDraftViewer drafts={packageDrafts(pkg)} fallbackSubject={pkg.title} />
            <div className="row gap-s wrap">
              <button type="button" className="btn btn-ghost" onClick={() => downloadPackage(pkg)}>
                <Icon name="download" size={15} /> {t('escalate.downloadPackage')}
              </button>
              {loading || pending ? <Spinner size={14} label={t('common.updating')} /> : null}
            </div>
            {error ? (
              <p className="field-error" role="alert">
                {error}
              </p>
            ) : null}
          </>
        )}
      </div>
    </dialog>
  );
}
