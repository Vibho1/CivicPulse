import { useEffect, useState, type FormEvent } from 'react';
import { api, errorMessage, type Cluster, type EscalationChannel, type EscalationDraft, type FormFile } from '../api';
import { copyText } from '../lib/csv';
import type { PreparedPhoto } from '../lib/image';
import { getRequesterName, setRequesterName } from '../lib/storage';
import { Icon } from './Icon';
import { PhotoInput } from './PhotoInput';
import { useToast } from './Toast';
import { Spinner } from './ui';

// --------------------------------------------------------------- escalation --

const CHANNELS: { id: EscalationChannel; label: string; icon: 'mail' | 'x' | 'file-text'; blurb: string }[] = [
  { id: 'email', label: 'Email', icon: 'mail', blurb: 'Formal complaint to the responsible engineer, with the evidence trail.' },
  { id: 'x', label: 'X post', icon: 'x', blurb: 'Short public nudge tagging the agency handle.' },
  { id: 'rti', label: 'RTI', icon: 'file-text', blurb: 'Right to Information request for work orders and closure records.' },
];

function looksLikeEmail(s: string | null): boolean {
  return !!s && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s.trim());
}

export function EscalationPanel({ cluster, onClose }: { cluster: Cluster; onClose: () => void }) {
  const toast = useToast();
  const [channel, setChannel] = useState<EscalationChannel>('email');
  const [name, setName] = useState(() => getRequesterName());
  const [busy, setBusy] = useState(false);
  const [drafts, setDrafts] = useState<Partial<Record<EscalationChannel, { draft: EscalationDraft; ai_mode: string }>>>({});
  const current = drafts[channel];

  useEffect(() => setRequesterName(name), [name]);

  async function generate() {
    setBusy(true);
    try {
      const res = await api.escalate(cluster.id, { channel, requester_name: name.trim() || undefined });
      setDrafts((d) => ({ ...d, [channel]: { draft: res.draft, ai_mode: res.ai_mode } }));
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function copyAll() {
    if (!current) return;
    const { draft } = current;
    const parts = [draft.to ? `To: ${draft.to}` : null, draft.subject ? `Subject: ${draft.subject}` : null, '', draft.body].filter((x) => x !== null);
    const ok = await copyText(parts.join('\n'));
    if (ok) toast.success('Copied to clipboard');
    else toast.error('Could not copy — select the text manually.');
  }

  const draft = current?.draft;
  const mailto = draft
    ? `mailto:${looksLikeEmail(draft.to) ? encodeURIComponent(draft.to!.trim()) : ''}?subject=${encodeURIComponent(draft.subject ?? `CivicPulse ${cluster.id}: ${cluster.title}`)}&body=${encodeURIComponent(draft.body)}`
    : null;
  const tweet = draft ? `https://twitter.com/intent/tweet?text=${encodeURIComponent(draft.body)}` : null;

  return (
    <div className="panel" role="region" aria-label="Draft escalation">
      <div className="panel-head">
        <h3>
          <Icon name="send" size={16} /> Draft an escalation
        </h3>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
          <Icon name="x" size={16} />
        </button>
      </div>

      <div className="tabs" role="tablist" aria-label="Channel">
        {CHANNELS.map((c) => (
          <button key={c.id} type="button" role="tab" aria-selected={channel === c.id} className={`tab${channel === c.id ? ' active' : ''}`} onClick={() => setChannel(c.id)}>
            <Icon name={c.icon} size={15} /> {c.label}
          </button>
        ))}
      </div>
      <p className="muted small">{CHANNELS.find((c) => c.id === channel)?.blurb}</p>

      <div className="row gap-s wrap">
        <label className="field grow">
          <span className="field-label">Your name (optional)</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="A concerned resident" />
        </label>
        <button type="button" className="btn btn-primary" onClick={() => void generate()} disabled={busy}>
          {busy ? <Spinner size={16} /> : <Icon name="spark" size={16} />} {draft ? 'Regenerate' : 'Generate draft'}
        </button>
      </div>

      {draft ? (
        <div className="draft">
          {draft.to ? (
            <div className="draft-line">
              <span className="muted">To:</span> {draft.to}
            </div>
          ) : null}
          {draft.subject ? (
            <div className="draft-line">
              <span className="muted">Subject:</span> {draft.subject}
            </div>
          ) : null}
          <textarea className="textarea draft-body" readOnly value={draft.body} rows={channel === 'x' ? 5 : 12} aria-label="Draft body" />
          <div className="row gap-s wrap">
            <button type="button" className="btn btn-secondary" onClick={() => void copyAll()}>
              <Icon name="copy" size={15} /> Copy
            </button>
            {channel === 'email' && mailto ? (
              <a className="btn btn-ghost" href={mailto}>
                <Icon name="mail" size={15} /> Open in mail app
              </a>
            ) : null}
            {channel === 'x' && tweet ? (
              <a className="btn btn-ghost" href={tweet} target="_blank" rel="noopener noreferrer">
                <Icon name="external" size={15} /> Post on X
              </a>
            ) : null}
            <span className="muted small">{current?.ai_mode.startsWith('gemini') ? 'Drafted by Gemini' : 'Template draft (offline mode)'}</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ resolve --

export function ResolvePanel({ busy, onSubmit, onClose }: { busy: boolean; onSubmit: (input: { after_photo?: FormFile; note?: string; actor?: string }) => Promise<void>; onClose: () => void }) {
  const [photo, setPhoto] = useState<PreparedPhoto | null>(null);
  const [note, setNote] = useState('');
  const [actor, setActor] = useState('ward-engineer');

  function submit(e: FormEvent) {
    e.preventDefault();
    void onSubmit({
      after_photo: photo ? { blob: photo.blob, filename: 'after.jpg' } : undefined,
      note: note.trim() || undefined,
      actor: actor.trim() || undefined,
    });
  }

  return (
    <form className="panel panel-official" onSubmit={submit} aria-label="Mark resolved">
      <div className="panel-head">
        <h3>
          <Icon name="check-circle" size={16} /> Mark resolved
        </h3>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
          <Icon name="x" size={16} />
        </button>
      </div>
      <p className="muted small">
        Upload the after-repair photo. Gemini compares it with the citizen's before-photo: same spot? really fixed? proper repair or cosmetic patch? The verdict is public.
      </p>
      <PhotoInput value={photo} onChange={setPhoto} label="After photo" captureLabel="Take after-photo" hint="Without a photo the closure is recorded as “no proof provided” and citizens are asked to verify." disabled={busy} />
      <label className="field">
        <span className="field-label">Resolution note</span>
        <textarea className="textarea" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Pothole filled with hot-mix asphalt and compacted." disabled={busy} />
      </label>
      <label className="field">
        <span className="field-label">Acting as</span>
        <input className="input" value={actor} onChange={(e) => setActor(e.target.value)} disabled={busy} />
      </label>
      <div className="row gap-s wrap">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? <Spinner size={16} /> : <Icon name="eye" size={16} />} {busy ? 'Running AI closure check…' : photo ? 'Resolve & run closure check' : 'Resolve without proof'}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// ------------------------------------------------------------------- verify --

export function VerifyPanel({ busy, onSubmit, onClose }: { busy: boolean; onSubmit: (input: { photo: FormFile; note?: string }) => Promise<void>; onClose: () => void }) {
  const [photo, setPhoto] = useState<PreparedPhoto | null>(null);
  const [note, setNote] = useState('');

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!photo) return;
    void onSubmit({ photo: { blob: photo.blob, filename: 'proof.jpg' }, note: note.trim() || undefined });
  }

  return (
    <form className="panel" onSubmit={submit} aria-label="Submit proof photo">
      <div className="panel-head">
        <h3>
          <Icon name="camera" size={16} /> Submit a proof photo
        </h3>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
          <Icon name="x" size={16} />
        </button>
      </div>
      <p className="muted small">Stand where the original photo was taken. Gemini checks it is the same spot and whether the fix is real. A confirmed fix closes the issue as verified.</p>
      <PhotoInput value={photo} onChange={setPhoto} label="Proof photo" captureLabel="Take proof photo" disabled={busy} />
      <label className="field">
        <span className="field-label">Note (optional)</span>
        <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Still open, just gravel thrown in." disabled={busy} />
      </label>
      <div className="row gap-s wrap">
        <button type="submit" className="btn btn-primary" disabled={busy || !photo}>
          {busy ? <Spinner size={16} /> : <Icon name="shield" size={16} />} {busy ? 'Checking…' : 'Submit for verification'}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}
