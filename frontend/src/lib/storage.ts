const REPORTER_KEY = 'civicpulse.reporter_id';
const OFFICIAL_KEY = 'civicpulse.official_mode';
const NAME_KEY = 'civicpulse.requester_name';

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // private mode / quota: ignore, the session still works
  }
}

function randomToken(len = 8): string {
  const alphabet = 'abcdefghjkmnpqrstuvwxyz23456789';
  const bytes = new Uint8Array(len);
  if (typeof crypto !== 'undefined' && 'getRandomValues' in crypto) crypto.getRandomValues(bytes);
  else for (let i = 0; i < len; i++) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join('');
}

/** Stable anonymous id for this browser, e.g. "anon-k7m2p9xw". */
export function getReporterId(): string {
  const existing = safeGet(REPORTER_KEY);
  if (existing) return existing;
  const id = `anon-${randomToken()}`;
  safeSet(REPORTER_KEY, id);
  return id;
}

export function getOfficialMode(): boolean {
  return safeGet(OFFICIAL_KEY) === '1';
}

export function setOfficialMode(on: boolean): void {
  safeSet(OFFICIAL_KEY, on ? '1' : '0');
}

export function getRequesterName(): string {
  return safeGet(NAME_KEY) ?? '';
}

export function setRequesterName(name: string): void {
  safeSet(NAME_KEY, name);
}
