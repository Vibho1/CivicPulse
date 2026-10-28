import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, errorMessage, type Cluster, type EscalationChannel, type EscalationDraft, type EscalationPackage, type FormFile } from '../api';
import { useI18n } from '../i18n';
import { copyText, downloadText } from '../lib/csv';
import type { PhotoExif } from '../lib/exif';
import type { PreparedPhoto } from '../lib/image';
import { getRequesterName, setRequesterName } from '../lib/storage';
import { useDebounced } from '../lib/useDebounced';
import { Icon } from './Icon';
import { PhotoInput } from './PhotoInput';
import { useToast } from './Toast';
import { Spinner } from './ui';

// --------------------------------------------------------------- escalation --

/** Labels and blurbs are `escalate.channel.<id>` / `escalate.blurb.<id>`. */
const CHANNELS: { id: EscalationChannel; icon: 'mail' | 'x' | 'file-text' }[] = [
  { id: 'email', icon: 'mail' },
  { id: 'x', icon: 'x' },
  { id: 'rti', icon: 'file-text' },
];

/** Max length of an X post. */
const X_LIMIT = 280;
/** X counts every link as this many characters (t.co wrapping). */
const X_URL_LENGTH = 23;

function looksLikeEmail(s: string | null): boolean {
  return !!s && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s.trim());
}

/** Length as X counts it: links are 23 characters, most CJK and emoji count double. */
function xLength(text: string): number {
  let n = 0;
  const rest = text.replace(/https?:\/\/\S+/gi, () => {
    n += X_URL_LENGTH;
    return '';
  });
  for (const ch of rest) {
    const cp = ch.codePointAt(0) ?? 0;
    const single = cp <= 0x10ff || (cp >= 0x2000 && cp <= 0x200d) || (cp >= 0x2010 && cp <= 0x201f) || (cp >= 0x2032 && cp <= 0x2037);
    n += single ? 1 : 2;
  }
  return n;
}

/** Clipboard text for a draft: To/Subject headers (when present), then the body. Kept in English, like the draft itself. */
function draftText(d: EscalationDraft): string {
  const head = [d.to ? `To: ${d.to}` : null, d.subject ? `Subject: ${d.subject}` : null].filter((x): x is string => x !== null);
  return head.length ? `${head.join('\n')}\n\n${d.body}` : d.body;
}

/** A draft and where it came from: the instant template, or a Gemini rewrite. */
export interface DraftEntry {
  draft: EscalationDraft;
  source: 'template' | 'gemini';
}

export type DraftSet = Partial<Record<EscalationChannel, DraftEntry>>;

/** An escalation package's three template drafts, keyed by channel. */
export function packageDrafts(pkg: EscalationPackage): DraftSet {
  const out: DraftSet = {};
  for (const c of CHANNELS) {
    const d = pkg.drafts?.[c.id];
    if (d) out[c.id] = { draft: d, source: 'template' };
  }
  return out;
}

/** Saves the package's all-in-one .txt. */
export function downloadPackage(pkg: EscalationPackage): void {
  downloadText(pkg.filename || 'civicpulse-escalation.txt', pkg.text, 'text/plain;charset=utf-8');
}

/**
 * Tabbed email / X / RTI drafts with Copy, "Open in mail app", "Post on X" and an
 * X character count. Shared by the issue and ward escalation packages; pass
 * `onRewrite` to offer a per-channel Gemini rewrite.
 */
export function EscalationDraftViewer({
  drafts,
  fallbackSubject,
  onRewrite,
  rewriting = null,
  rewriteDisabled = false,
}: {
  drafts: DraftSet;
  /** Mail subject for drafts that have none. */
  fallbackSubject: string;
  onRewrite?: (channel: EscalationChannel) => void;
  /** Channel whose Gemini rewrite is in flight. */
  rewriting?: EscalationChannel | null;
  rewriteDisabled?: boolean;
}) {
  const toast = useToast();
  const { t } = useI18n();
  const [channel, setChannel] = useState<EscalationChannel>('email');
  const channelLabel = t(`escalate.channel.${channel}`);
  const entry = drafts[channel];
  const draft = entry?.draft ?? null;

  async function copy() {
    if (!draft) return;
    const ok = await copyText(draftText(draft));
    if (ok) toast.success(t('common.copied'));
    else toast.error(t('common.copyFailed'));
  }

  const mailto = draft
    ? `mailto:${looksLikeEmail(draft.to) ? encodeURIComponent(draft.to!.trim()) : ''}?subject=${encodeURIComponent(draft.subject ?? fallbackSubject)}&body=${encodeURIComponent(draft.body)}`
    : null;
  const tweet = draft ? `https://twitter.com/intent/tweet?text=${encodeURIComponent(draft.body)}` : null;
  const xLen = draft && channel === 'x' ? xLength(draft.body) : 0;

  return (
    <>
      <div className="tabs" role="tablist" aria-label={t('escalate.channels')}>
        {CHANNELS.map((c) => (
          <button key={c.id} type="button" role="tab" aria-selected={channel === c.id} className={`tab${channel === c.id ? ' active' : ''}`} onClick={() => setChannel(c.id)}>
            <Icon name={c.icon} size={15} /> {t(`escalate.channel.${c.id}`)}
            {drafts[c.id]?.source === 'gemini' ? <Icon name="spark" size={12} title={t('escalate.geminiRewrite')} /> : null}
          </button>
        ))}
      </div>
      <p className="muted small">{t(`escalate.blurb.${channel}`)}</p>

      {entry && draft ? (
        <div className="draft">
          <div className="chips draft-meta">
            {entry.source === 'gemini' ? (
              <span className="chip chip-info" title={t('escalate.geminiRewriteTitle')}>
                <Icon name="spark" size={12} /> {t('escalate.geminiRewrite')}
              </span>
            ) : (
              <span className="chip chip-muted" title={t('escalate.templateDraftTitle')}>
                <Icon name="file-text" size={12} /> {t('escalate.templateDraft')}
              </span>
            )}
            {channel === 'x' ? (
              <span className={`chip ${xLen > X_LIMIT ? 'chip-bad' : 'chip-ok'}`} title={t('escalate.xCountTitle')}>
                {t('escalate.xCount', { count: xLen, limit: X_LIMIT })}
              </span>
            ) : null}
          </div>
          {draft.to ? (
            <div className="draft-line">
              <span className="muted">{t('escalate.to')}</span> {draft.to}
            </div>
          ) : null}
          {draft.subject ? (
            <div className="draft-line">
              <span className="muted">{t('escalate.subject')}</span> {draft.subject}
            </div>
          ) : null}
          <textarea className="textarea draft-body" readOnly value={draft.body} rows={channel === 'x' ? 5 : 12} aria-label={t('escalate.bodyLabel', { channel: channelLabel })} />
          <div className="row gap-s wrap">
            <button type="button" className="btn btn-secondary" onClick={() => void copy()}>
              <Icon name="copy" size={15} /> {t('common.copy')}
            </button>
            {channel === 'email' && mailto ? (
              <a className="btn btn-ghost" href={mailto}>
                <Icon name="mail" size={15} /> {t('escalate.openMail')}
              </a>
            ) : null}
            {channel === 'x' && tweet ? (
              <a className="btn btn-ghost" href={tweet} target="_blank" rel="noopener noreferrer">
                <Icon name="external" size={15} /> {t('escalate.postX')}
              </a>
            ) : null}
            {onRewrite ? (
              <button type="button" className="btn btn-ghost" onClick={() => onRewrite(channel)} disabled={rewriteDisabled || rewriting !== null} title={t('escalate.rewriteTitle')}>
                {rewriting === channel ? <Spinner size={15} /> : <Icon name="spark" size={15} />} {entry.source === 'gemini' ? t('escalate.rewriteAgain') : t('escalate.rewrite')}
              </button>
            ) : null}
          </div>
        </div>
      ) : (
        <p className="muted small">{t('escalate.noDraft', { channel: channelLabel })}</p>
      )}
    </>
  );
}

export function EscalationPanel({ cluster, onClose }: { cluster: Cluster; onClose: () => void }) {
  const toast = useToast();
  const { t } = useI18n();
  const [name, setName] = useState(() => getRequesterName());
  const requester = useDebounced(name.trim(), 600);
  const [pkg, setPkg] = useState<EscalationPackage | null>(null);
  const [drafts, setDrafts] = useState<DraftSet>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rewriting, setRewriting] = useState<EscalationChannel | null>(null);
  const [attempt, setAttempt] = useState(0);
  // Bumped per package load (and on unmount) so late responses can't overwrite fresher drafts.
  const generation = useRef(0);

  useEffect(() => setRequesterName(name), [name]);

  // Instant template package on open; regenerated when the (debounced) name changes.
  useEffect(() => {
    const gen = ++generation.current;
    setLoading(true);
    setError(null);
    api
      .escalationPackage(cluster.id, { requester_name: requester || undefined })
      .then((p) => {
        if (gen !== generation.current) return;
        setPkg(p);
        setDrafts(packageDrafts(p));
      })
      .catch((e: unknown) => {
        if (gen === generation.current) setError(errorMessage(e));
      })
      .finally(() => {
        if (gen === generation.current) setLoading(false);
      });
    return () => {
      generation.current++;
    };
  }, [cluster.id, requester, attempt]);

  async function rewrite(channel: EscalationChannel) {
    const gen = generation.current;
    setRewriting(channel);
    try {
      const res = await api.escalate(cluster.id, { channel, requester_name: requester || undefined, ai: true });
      if (gen !== generation.current) return;
      const gemini = res.ai_mode.startsWith('gemini');
      const next: DraftEntry = { draft: res.draft, source: gemini ? 'gemini' : 'template' };
      setDrafts((d) => {
        const copy: DraftSet = { ...d };
        copy[channel] = next;
        return copy;
      });
      if (!gemini) toast.info(t('escalate.geminiUnavailable'));
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setRewriting(null);
    }
  }

  const pending = name.trim() !== requester; // waiting for the debounce
  const rewritten = Object.values(drafts).some((d) => d?.source === 'gemini');

  return (
    <div className="panel" role="region" aria-label={t('escalate.package')}>
      <div className="panel-head">
        <h3>
          <Icon name="send" size={16} /> {t('escalate.package')}
        </h3>
        <button type="button" className="icon-btn" onClick={onClose} aria-label={t('common.close')}>
          <Icon name="x" size={16} />
        </button>
      </div>
      <p className="muted small">{t('escalate.packageIntro')}</p>

      <label className="field">
        <span className="field-label">{t('escalate.name')}</span>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={t('escalate.namePlaceholder')} maxLength={80} autoComplete="name" />
      </label>

      {!pkg ? (
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
          <Spinner label={t('escalate.preparing')} />
        )
      ) : (
        <>
          <EscalationDraftViewer
            drafts={drafts}
            fallbackSubject={`CivicPulse ${cluster.id}: ${cluster.title}`}
            onRewrite={(ch) => void rewrite(ch)}
            rewriting={rewriting}
            rewriteDisabled={loading || pending}
          />
          <div className="row gap-s wrap">
            <button type="button" className="btn btn-ghost" onClick={() => downloadPackage(pkg)}>
              <Icon name="download" size={15} /> {t('escalate.downloadPackage')}
            </button>
            {loading || pending ? <Spinner size={14} label={t('common.updating')} /> : null}
          </div>
          {rewritten ? <p className="muted small">{t('escalate.txtNote')}</p> : null}
          {error ? (
            <p className="field-error" role="alert">
              {error}
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ resolve --

/** What the resolve panel hands back: the after-photo plus its original file's EXIF. */
export interface ResolvePanelInput {
  after_photo?: FormFile;
  /** EXIF of the original after-photo file; absent without a photo. */
  exif?: PhotoExif;
  note?: string;
  actor?: string;
}

export function ResolvePanel({ busy, onSubmit, onClose }: { busy: boolean; onSubmit: (input: ResolvePanelInput) => Promise<void>; onClose: () => void }) {
  const { t } = useI18n();
  const [photo, setPhoto] = useState<PreparedPhoto | null>(null);
  const [note, setNote] = useState('');
  const [actor, setActor] = useState('ward-engineer');

  function submit(e: FormEvent) {
    e.preventDefault();
    void onSubmit({
      after_photo: photo ? { blob: photo.blob, filename: 'after.jpg' } : undefined,
      exif: photo?.exif,
      note: note.trim() || undefined,
      actor: actor.trim() || undefined,
    });
  }

  return (
    <form className="panel panel-official" onSubmit={submit} aria-label={t('resolve.title')}>
      <div className="panel-head">
        <h3>
          <Icon name="check-circle" size={16} /> {t('resolve.title')}
        </h3>
        <button type="button" className="icon-btn" onClick={onClose} aria-label={t('common.close')}>
          <Icon name="x" size={16} />
        </button>
      </div>
      <p className="muted small">{t('resolve.hint')}</p>
      <PhotoInput value={photo} onChange={setPhoto} label={t('resolve.photoLabel')} captureLabel={t('resolve.capture')} hint={t('resolve.photoHint')} disabled={busy} />
      <label className="field">
        <span className="field-label">{t('resolve.noteLabel')}</span>
        <textarea className="textarea" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('resolve.notePlaceholder')} disabled={busy} />
      </label>
      <label className="field">
        <span className="field-label">{t('resolve.actorLabel')}</span>
        <input className="input" value={actor} onChange={(e) => setActor(e.target.value)} disabled={busy} />
      </label>
      <div className="row gap-s wrap">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? <Spinner size={16} /> : <Icon name="eye" size={16} />} {busy ? t('resolve.running') : photo ? t('resolve.submitPhoto') : t('resolve.submitNoPhoto')}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
          {t('common.cancel')}
        </button>
      </div>
    </form>
  );
}

// ------------------------------------------------------------------- verify --

/** What the verify panel hands back: the proof photo plus its original file's EXIF. */
export interface VerifyPanelInput {
  photo: FormFile;
  /** EXIF of the original proof-photo file. */
  exif: PhotoExif;
  note?: string;
}

export function VerifyPanel({ busy, onSubmit, onClose }: { busy: boolean; onSubmit: (input: VerifyPanelInput) => Promise<void>; onClose: () => void }) {
  const { t } = useI18n();
  const [photo, setPhoto] = useState<PreparedPhoto | null>(null);
  const [note, setNote] = useState('');

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!photo) return;
    void onSubmit({ photo: { blob: photo.blob, filename: 'proof.jpg' }, exif: photo.exif, note: note.trim() || undefined });
  }

  return (
    <form className="panel" onSubmit={submit} aria-label={t('verify.title')}>
      <div className="panel-head">
        <h3>
          <Icon name="camera" size={16} /> {t('verify.heading')}
        </h3>
        <button type="button" className="icon-btn" onClick={onClose} aria-label={t('common.close')}>
          <Icon name="x" size={16} />
        </button>
      </div>
      <p className="muted small">{t('verify.hint')}</p>
      <PhotoInput value={photo} onChange={setPhoto} label={t('verify.photoLabel')} captureLabel={t('verify.capture')} disabled={busy} />
      <label className="field">
        <span className="field-label">{t('verify.noteLabel')}</span>
        <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('verify.notePlaceholder')} disabled={busy} />
      </label>
      <div className="row gap-s wrap">
        <button type="submit" className="btn btn-primary" disabled={busy || !photo}>
          {busy ? <Spinner size={16} /> : <Icon name="shield" size={16} />} {busy ? t('verify.checking') : t('verify.submit')}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
          {t('common.cancel')}
        </button>
      </div>
    </form>
  );
}
