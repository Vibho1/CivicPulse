/**
 * Typed client for the CivicPulse API (see docs/API.md).
 *
 * All helpers use relative URLs (`/api/...`) so the same build works behind the
 * Vite dev proxy and when FastAPI serves `frontend/dist` directly. Set
 * `VITE_API_BASE` to point at a different origin.
 */

// ---------------------------------------------------------------- vocabulary --

export type Category =
  | 'pothole'
  | 'road_damage'
  | 'footpath_damage'
  | 'streetlight'
  | 'garbage'
  | 'water_leak'
  | 'sewage_overflow'
  | 'open_drain_manhole'
  | 'waterlogging'
  | 'fallen_tree'
  | 'power_hazard'
  | 'traffic_signal'
  | 'other';

export type Agency =
  | 'GBA_ROADS'
  | 'GBA_SWM'
  | 'GBA_SWD'
  | 'GBA_ELECTRICAL'
  | 'GBA_FORESTRY'
  | 'BWSSB'
  | 'BESCOM'
  | 'BMRCL'
  | 'TRAFFIC_POLICE';

export type ClusterStatus =
  | 'open'
  | 'in_progress'
  | 'resolved_pending_verification'
  | 'resolved_verified'
  | 'closure_disputed';

export const ALL_STATUSES: ClusterStatus[] = [
  'open',
  'in_progress',
  'resolved_pending_verification',
  'resolved_verified',
  'closure_disputed',
];

export function isClusterStatus(v: string): v is ClusterStatus {
  return (ALL_STATUSES as string[]).includes(v);
}

export type Verdict =
  | 'VERIFIED'
  | 'UNVERIFIED_DIFFERENT_LOCATION'
  | 'UNVERIFIED_NOT_FIXED'
  | 'UNVERIFIED_COSMETIC'
  | 'INCONCLUSIVE'
  | 'NO_PROOF_PROVIDED';

export type FixQuality = 'proper' | 'partial' | 'cosmetic' | 'none' | 'unknown';

export type EventType =
  | 'reported'
  | 'merged'
  | 'corroborated'
  | 'reopened'
  | 'status_changed'
  | 'resolved'
  | 'closure_check'
  | 'citizen_verification'
  | 'repeat_failure_flagged'
  | 'escalation_drafted';

export type EscalationChannel = 'email' | 'x' | 'rti';

export type AiMode = 'gemini' | 'heuristic';

// ------------------------------------------------------------------- objects --

export interface AgencyInfo {
  label: string;
  short: string;
  helpline: string;
  x_handle: string;
  email_hint: string;
  scope: string;
}

export interface ScoreComponent {
  component: string;
  points: number;
  reason: string;
}

export interface ScoreBreakdown {
  total: number;
  components: ScoreComponent[];
}

export interface ContextHit {
  name: string;
  type: string;
  distance_m: number;
}

export interface Cluster {
  id: string;
  title: string;
  category: Category;
  category_label: string;
  status: ClusterStatus;
  status_label: string;
  lat: number;
  lng: number;
  ward: string;
  zone: string | null;
  description: string | null;
  landmark: string | null;
  agency: Agency;
  agency_label: string;
  agency_short: string;
  agency_reason: string | null;
  agency_info: AgencyInfo;
  report_count: number;
  max_severity: number;
  impact_score: number;
  score_breakdown: ScoreBreakdown | null;
  hazards: string[];
  context: ContextHit[];
  sla_hours: number;
  sla_due_at: string;
  sla_breached: boolean;
  hours_open: number;
  hours_to_sla: number;
  repeat_failure: boolean;
  previous_cluster_id: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
  closure_count: number;
  verification_verdict: Verdict | null;
  verified_at: string | null;
  primary_photo_url: string | null;
  after_photo_url: string | null;
  first_report_id?: string | null;
}

export interface EvidenceFlags {
  recent_digging: boolean;
  utility_work_type: 'water_pipeline' | 'sewage' | 'power_cable' | 'metro' | 'telecom' | 'gas' | 'unknown' | 'none';
  photo_provided: boolean;
  photo_usable: boolean;
  photo_matches_description: boolean;
  people_or_plates_visible: boolean;
}

/** Raw structured output of the evidence parser (Gemini or heuristic). */
export interface Extraction {
  is_civic_issue: boolean;
  transcript: string;
  transcript_english: string;
  language: string;
  category: Category;
  severity: number;
  title: string;
  description: string;
  landmark: string | null;
  size_estimate: string | null;
  hazards: string[];
  evidence: EvidenceFlags;
  suggested_agency: Agency | null;
  agency_reasoning: string;
  confidence: number;
}

export interface Report {
  id: string;
  cluster_id: string;
  created_at: string;
  lat: number;
  lng: number;
  accuracy: number | null;
  reporter_id: string | null;
  text: string | null;
  transcript: string;
  transcript_english: string;
  language: string;
  category: Category;
  category_label: string;
  severity: number;
  title: string;
  description: string | null;
  landmark: string | null;
  size_estimate: string | null;
  hazards: string[];
  evidence: Partial<EvidenceFlags>;
  agency: Agency;
  agency_reason: string | null;
  ai_mode: string;
  confidence: number;
  ward: string;
  exif_gps: [number, number] | null;
  is_corroboration: boolean;
  photo_url: string | null;
  audio_url: string | null;
  extraction: Extraction | null;
}

export interface VerificationDetails {
  matched_cues?: string[];
  mismatch_cues?: string[];
  [key: string]: unknown;
}

export interface Verification {
  id: string;
  cluster_id: string;
  created_at: string;
  kind: 'official_closure' | 'citizen';
  actor: string;
  verdict: Verdict;
  same_location: boolean;
  issue_resolved: boolean;
  fix_quality: FixQuality;
  same_location_confidence: number;
  resolution_confidence: number;
  explanation: string;
  ai_mode: string;
  note: string | null;
  photo_url: string | null;
  before_photo_urls: (string | null)[];
  details: VerificationDetails;
}

export interface TimelineEvent {
  id: string;
  cluster_id: string;
  created_at: string;
  type: EventType | string;
  actor: string;
  note: string;
  payload: Record<string, unknown>;
}

export interface ClusterDetail {
  cluster: Cluster;
  reports: Report[];
  verifications: Verification[];
  events: TimelineEvent[];
  previous_cluster: Cluster | null;
}

export interface ClusterDetailWithVerification extends ClusterDetail {
  verification: Verification;
}

export interface ReportResponse {
  report: Report;
  cluster: Cluster;
  merged: boolean;
  reopened: boolean;
  repeat_failure: boolean;
  previous_cluster: Cluster | null;
  extraction: Extraction;
  ai_mode: string;
  location_warning: string | null;
}

export interface CorroborateResponse {
  cluster: Cluster;
  merged: boolean;
  report: Report;
}

export interface EscalationDraft {
  channel: EscalationChannel;
  subject: string | null;
  to: string | null;
  body: string;
}

export interface EscalationResponse {
  draft: EscalationDraft;
  ai_mode: string;
  context: Record<string, unknown>;
}

export interface Health {
  status: string;
  ai_mode: AiMode | string;
  model: string | null;
  last_ai_error: string | null;
  counts: Record<string, number>;
  demo_mode: boolean;
}

export interface MetaCategory {
  id: Category;
  label: string;
  sla_hours: number;
}

export interface MetaAgency extends AgencyInfo {
  id: Agency;
}

export interface MetaStatus {
  id: ClusterStatus;
  label: string;
}

export interface Ward {
  name: string;
  zone: string;
  lat: number;
  lng: number;
}

export interface DemoLocation {
  name: string;
  lat: number;
  lng: number;
}

export interface Meta {
  categories: MetaCategory[];
  agencies: MetaAgency[];
  statuses: MetaStatus[];
  verdicts: Verdict[];
  hazards: string[];
  repeat_failure_window_days: number;
  wards: Ward[];
  demo_locations: DemoLocation[];
}

export interface CityStats {
  clusters: number;
  reports: number;
  unresolved: number;
  closures: number;
  verified_closure_rate: number | null;
  unverified_closure_rate: number | null;
  sla_breached_open: number;
  repeat_failures: number;
  generated_at: string;
}

export interface WardRow {
  ward: string;
  zone: string;
  lat: number;
  lng: number;
  total: number;
  reports: number;
  open: number;
  in_progress: number;
  resolved_pending_verification: number;
  resolved_verified: number;
  closure_disputed: number;
  closures: number;
  verified_closure_rate: number | null;
  unverified_closure_rate: number | null;
  disputed_closure_rate: number | null;
  avg_hours_to_close: number | null;
  avg_hours_to_verified_fix: number | null;
  sla_breach_rate: number | null;
  sla_breached_open: number;
  repeat_failure_rate: number | null;
  avg_open_impact: number;
  top_agency: Agency;
}

export interface Scorecard {
  city: CityStats;
  wards: WardRow[];
}

export interface SeedSummary {
  status: string;
  clusters: number;
  counts: Record<string, number>;
  real_photos?: boolean;
  highlights?: Record<string, string>;
}

// -------------------------------------------------------------------- inputs --

export interface FormFile {
  blob: Blob;
  filename: string;
}

export interface NewReportInput {
  lat: number;
  lng: number;
  accuracy?: number | null;
  text?: string;
  reporter_id?: string;
  language_hint?: string;
  audio?: FormFile;
  photo?: FormFile;
}

export interface CorroborateInput {
  lat: number;
  lng: number;
  reporter_id?: string;
  text?: string;
  photo?: FormFile;
}

export interface StatusUpdate {
  status: 'open' | 'in_progress';
  note?: string;
  actor?: string;
}

export interface ResolveInput {
  note?: string;
  actor?: string;
  after_photo?: FormFile;
}

export interface VerifyInput {
  photo: FormFile;
  reporter_id?: string;
  note?: string;
}

export interface EscalateInput {
  channel: EscalationChannel;
  requester_name?: string;
}

export interface ClusterQuery {
  status?: ClusterStatus[];
  ward?: string;
  category?: string;
  agency?: string;
  limit?: number;
}

// -------------------------------------------------------------------- errors --

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  /** Populated for the 422 "not a civic issue / low confidence" shape. */
  readonly extraction: Extraction | null;

  constructor(status: number, message: string, detail: unknown, extraction: Extraction | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.extraction = extraction;
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function detailToMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    // FastAPI request-validation errors: [{loc, msg, type}]
    const parts = detail.map((d) => {
      if (isRecord(d) && typeof d.msg === 'string') {
        const loc = Array.isArray(d.loc)
          ? d.loc.filter((x): x is string => typeof x === 'string' && x !== 'body').join('.')
          : '';
        return loc ? `${loc}: ${d.msg}` : d.msg;
      }
      return String(d);
    });
    return parts.join('; ') || fallback;
  }
  if (isRecord(detail) && typeof detail.message === 'string') return detail.message;
  return fallback;
}

/** Human-readable message for any thrown value. */
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

// ------------------------------------------------------------------ transport --

const RAW_BASE = import.meta.env.VITE_API_BASE ?? '';
export const API_BASE = RAW_BASE.replace(/\/+$/, '');

/** Absolute-or-relative URL for `/uploads/...` media paths returned by the API. */
export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (/^(https?:)?\/\//i.test(path) || path.startsWith('blob:') || path.startsWith('data:')) return path;
  return `${API_BASE}${path.startsWith('/') ? '' : '/'}${path}`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api${path}`, { ...init, headers: { Accept: 'application/json', ...(init.headers ?? {}) } });
  } catch (e) {
    throw new ApiError(0, 'Cannot reach the CivicPulse API. Is the backend running on port 8000?', e);
  }
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!res.ok) {
    const detail = isRecord(body) && 'detail' in body ? body.detail : body;
    const extraction = isRecord(detail) && isRecord(detail.extraction) ? (detail.extraction as unknown as Extraction) : null;
    throw new ApiError(res.status, detailToMessage(detail, `${res.status} ${res.statusText || 'Request failed'}`), detail, extraction);
  }
  return body as T;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}

type FormValue = string | number | null | undefined | FormFile;

function buildForm(fields: Record<string, FormValue>): FormData {
  const fd = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    if (value === undefined || value === null || value === '') continue;
    if (typeof value === 'object') fd.append(key, value.blob, value.filename);
    else fd.append(key, String(value));
  }
  return fd;
}

function postForm<T>(path: string, fields: Record<string, FormValue>): Promise<T> {
  return request<T>(path, { method: 'POST', body: buildForm(fields) });
}

function clusterPath(id: string, suffix = ''): string {
  return `/clusters/${encodeURIComponent(id)}${suffix}`;
}

// ---------------------------------------------------------------- endpoints --

export const api = {
  health: () => request<Health>('/health'),
  meta: () => request<Meta>('/meta'),
  stats: () => request<CityStats>('/stats'),

  clusters: (q: ClusterQuery = {}) => {
    const params = new URLSearchParams();
    if (q.status && q.status.length) params.set('status', q.status.join(','));
    if (q.ward) params.set('ward', q.ward);
    if (q.category) params.set('category', q.category);
    if (q.agency) params.set('agency', q.agency);
    if (q.limit) params.set('limit', String(q.limit));
    const qs = params.toString();
    return request<{ clusters: Cluster[] }>(`/clusters${qs ? `?${qs}` : ''}`);
  },
  cluster: (id: string) => request<ClusterDetail>(clusterPath(id)),
  report: (id: string) => request<{ report: Report; cluster: Cluster }>(`/reports/${encodeURIComponent(id)}`),

  createReport: (input: NewReportInput) =>
    postForm<ReportResponse>('/reports', {
      lat: input.lat,
      lng: input.lng,
      accuracy: input.accuracy ?? undefined,
      text: input.text,
      reporter_id: input.reporter_id,
      language_hint: input.language_hint,
      audio: input.audio,
      photo: input.photo,
    }),

  corroborate: (id: string, input: CorroborateInput) =>
    postForm<CorroborateResponse>(clusterPath(id, '/corroborate'), {
      lat: input.lat,
      lng: input.lng,
      reporter_id: input.reporter_id,
      text: input.text,
      photo: input.photo,
    }),

  setStatus: (id: string, body: StatusUpdate) => postJson<ClusterDetail>(clusterPath(id, '/status'), body),

  resolve: (id: string, input: ResolveInput) =>
    postForm<ClusterDetailWithVerification>(clusterPath(id, '/resolve'), {
      note: input.note,
      actor: input.actor,
      after_photo: input.after_photo,
    }),

  verify: (id: string, input: VerifyInput) =>
    postForm<ClusterDetailWithVerification>(clusterPath(id, '/verify'), {
      photo: input.photo,
      reporter_id: input.reporter_id,
      note: input.note,
    }),

  escalate: (id: string, body: EscalateInput) => postJson<EscalationResponse>(clusterPath(id, '/escalate'), body),

  scorecard: () => request<Scorecard>('/wards/scorecard'),

  seed: (reset = true) => request<SeedSummary>(`/admin/seed?reset=${reset ? 'true' : 'false'}`, { method: 'POST' }),
  reset: () => request<{ status: string }>('/admin/reset', { method: 'POST' }),
};

export type Api = typeof api;
