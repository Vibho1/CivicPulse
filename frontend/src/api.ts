/**
 * Typed client for the CivicPulse API (see docs/API.md).
 *
 * All helpers use relative URLs (`/api/...`) so the same build works behind the
 * Vite dev proxy and when FastAPI serves `frontend/dist` directly. Set
 * `VITE_API_BASE` to point at a different origin.
 */

import { getLang, translate } from './i18n';

// ---------------------------------------------------------------- vocabulary --

/** Issue categories; the first seven are the PRD enum, the rest are CivicPulse extensions. */
export type Category =
  | 'pothole'
  | 'unrestored_utility_trench'
  | 'streetlight_outage'
  | 'garbage_dump'
  | 'waterlogging'
  | 'damaged_footpath'
  | 'fallen_tree'
  | 'road_damage'
  | 'water_leak'
  | 'sewage_overflow'
  | 'open_drain_manhole'
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

/** PRD agency codes. The PRD predates the 2025 BBMP → GBA rename, hence `BBMP_*`. */
export type AgencyCode =
  | 'BBMP_ROADS'
  | 'BBMP_SWM'
  | 'BBMP_SWD'
  | 'BBMP_ELECTRICAL'
  | 'BBMP_FORESTRY'
  | 'BWSSB'
  | 'BESCOM'
  | 'BMRCL'
  | 'BTP';

/** Agency id → PRD code (mirrors the backend; used when a payload lacks `agency_code`). */
export const AGENCY_CODES: Record<Agency, AgencyCode> = {
  GBA_ROADS: 'BBMP_ROADS',
  GBA_SWM: 'BBMP_SWM',
  GBA_SWD: 'BBMP_SWD',
  GBA_ELECTRICAL: 'BBMP_ELECTRICAL',
  GBA_FORESTRY: 'BBMP_FORESTRY',
  BWSSB: 'BWSSB',
  BESCOM: 'BESCOM',
  BMRCL: 'BMRCL',
  TRAFFIC_POLICE: 'BTP',
};

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

/** Overall repair grade of a closure proof (combines the fix and the location check). */
export type RepairQuality = 'verified_complete' | 'temporary_or_partial' | 'unrepaired' | 'mismatched_location';

/** Where a proof photo's location came from: its EXIF GPS or the capturing device. */
export type GpsSource = 'exif' | 'device';

/** `max_severity` (1-5) bucketed. */
export type SeverityLevel = 'low' | 'medium' | 'high' | 'critical';

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
  | 'escalation_drafted'
  | 'verification_requested'
  | 'external_ref_recorded';

export type EscalationChannel = 'email' | 'x' | 'rti';

export type AiMode = 'gemini' | 'heuristic';

export type NotificationStatus = 'unread' | 'read' | 'expired';

/** Server-side photo provenance checks recorded on a report. */
export type PhotoFlag = 'exif_stripped' | 'exif_location_far' | 'stock_or_screenshot' | 'faces_or_plates_blurred';

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
  /** 'unique_reporters' | 'severity' | 'context' | 'days_elapsed' (PRD weights; see `Meta.score_weights`). */
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
  /** PRD code of `agency`, e.g. 'BBMP_ROADS' for GBA_ROADS or 'BTP' for TRAFFIC_POLICE. */
  agency_code: AgencyCode;
  agency_label: string;
  agency_short: string;
  agency_reason: string | null;
  agency_info: AgencyInfo;
  /** Co-owner of the fix, e.g. GBA_ROADS resurfacing after a BWSSB pipe repair. */
  secondary_agency: Agency | null;
  secondary_agency_code: AgencyCode | null;
  secondary_agency_reason: string | null;
  secondary_agency_label: string | null;
  secondary_agency_short: string | null;
  secondary_agency_info: AgencyInfo | null;
  /** 0..1 confidence in the agency routing; null when not scored. */
  routing_confidence: number | null;
  /** Reports filed (the same citizen reporting twice counts twice). */
  report_count: number;
  /** Unique citizens behind those reports. */
  reporter_count: number;
  max_severity: number;
  severity_level: SeverityLevel;
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
  /** Official grievance system the issue was also filed on, e.g. 'sahaaya'. */
  external_system: string | null;
  /** Complaint number in that system. */
  external_ref: string | null;
  external_ref_at: string | null;
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

/** Size estimate from the parser, in centimetres; any part may be unknown. */
export interface EstimatedDimensionsCm {
  length: number | null;
  width: number | null;
  depth: number | null;
}

/** PRD-shaped parser output stored with each report. */
export interface ParsedReport {
  category: Category;
  severity: SeverityLevel;
  estimated_dimensions_cm: EstimatedDimensionsCm | null;
  extracted_landmark: string | null;
  transcription: string;
  language: string;
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
  severity_level: SeverityLevel;
  title: string;
  description: string | null;
  landmark: string | null;
  size_estimate: string | null;
  hazards: string[];
  evidence: Partial<EvidenceFlags>;
  agency: Agency;
  /** PRD code of `agency`. */
  agency_code: AgencyCode;
  agency_reason: string | null;
  secondary_agency: Agency | null;
  secondary_agency_reason: string | null;
  /** 0..1 confidence in this report's agency routing. */
  routing_confidence: number | null;
  ai_mode: string;
  confidence: number;
  ward: string;
  exif_gps: [number, number] | null;
  is_corroboration: boolean;
  photo_url: string | null;
  /** Only in the reporter's own POST response, or when the server sets PUBLIC_AUDIO=true. */
  audio_url: string | null;
  extraction: Extraction | null;
  /** PRD-shaped parser output (category, severity bucket, size, landmark, transcription). */
  parsed: ParsedReport | null;
  /** Photo provenance checks, e.g. 'exif_stripped' for a forwarded/stock photo. */
  photo_flags: PhotoFlag[];
  /** Face / number-plate regions blurred before the photo was stored. */
  privacy_blurred: number;
  /** 0..1 track record of this reporter; null for anonymous reporters. */
  reporter_credibility: number | null;
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
  // Proof-photo GPS check and repair grade. Optional: verifications recorded
  // before these existed may not carry them.
  /** Photo GPS is within `limits.verify_gps_radius_m` of the issue. */
  location_match?: boolean;
  /** Metres between the photo's GPS fix and the issue location; null = no GPS. */
  gps_distance_m?: number | null;
  /** Where the photo location came from; null = the photo had no GPS. */
  gps_source?: GpsSource | null;
  repair_quality?: RepairQuality | null;
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

/** Set on a new report that looks like an emergency (someone hurt or in immediate danger). */
export interface EmergencyNotice {
  is_emergency: boolean;
  /** Number to call, '112'. */
  number: string;
  message: string;
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
  /** CivicPulse does not dispatch emergency services: the UI tells the reporter to call 112. */
  emergency: EmergencyNotice | null;
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

/** One issue inside an escalation package. */
export interface EscalationPackageCluster {
  id: string;
  title: string;
  status: ClusterStatus;
  status_label: string;
  agency: Agency;
  agency_code: AgencyCode;
  agency_label: string;
  /** Why it is being escalated, e.g. the failed closure check or the SLA breach. */
  failure_reason: string | null;
  sla_breached: boolean;
  /** Absolute CivicPulse link to the issue. */
  url: string;
}

/** Instant, template-based email + X + RTI drafts for one issue or a whole ward. */
export interface EscalationPackage {
  scope: 'cluster' | 'ward';
  ward: string;
  ward_number: number | null;
  title: string;
  cluster_ids: string[];
  clusters: EscalationPackageCluster[];
  drafts: Record<EscalationChannel, EscalationDraft>;
  /** All three drafts, ready to save as .txt. */
  text: string;
  /** Suggested download name, e.g. 'civicpulse-escalation-CP-ABC123-2026-10-28.txt'. */
  filename: string;
  generated_at: string;
  elapsed_ms: number;
  /** 'template' (Gemini rewrites go through `api.escalate`). */
  ai_mode: string;
}

/** Optional integrations enabled on the server. */
export interface HealthFeatures {
  whatsapp: boolean;
  /** Voice-note audio is public; otherwise only the reporter sees their recording. */
  public_audio: boolean;
  /** Faces and number plates are blurred before photos are stored. */
  face_blur: boolean;
}

export interface Health {
  status: string;
  ai_mode: AiMode | string;
  model: string | null;
  last_ai_error: string | null;
  counts: Record<string, number>;
  demo_mode: boolean;
  features: HealthFeatures;
}

export interface MetaCategory {
  id: Category;
  label: string;
  sla_hours: number;
  /** One of the seven PRD categories (the rest are CivicPulse extensions). */
  prd: boolean;
}

export interface MetaAgency extends AgencyInfo {
  id: Agency;
  /** PRD agency code, e.g. 'BBMP_ROADS'. */
  code: AgencyCode;
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
  /** Official ward number; null until the official ward GeoJSON lands (PRD OQ-2). */
  number: number | null;
}

export interface DemoLocation {
  name: string;
  lat: number;
  lng: number;
}

/** Upload, duplicate-guard and proof-photo limits enforced by the API. */
export interface Limits {
  max_image_mb: number;
  max_audio_s: number;
  duplicate_window_s: number;
  duplicate_radius_m: number;
  verify_gps_radius_m: number;
}

/** Backend defaults, for when `meta` has not loaded (or predates `limits`). */
export const DEFAULT_LIMITS: Limits = {
  max_image_mb: 10,
  max_audio_s: 30,
  duplicate_window_s: 300,
  duplicate_radius_m: 1000,
  verify_gps_radius_m: 50,
};

export interface Meta {
  categories: MetaCategory[];
  agencies: MetaAgency[];
  statuses: MetaStatus[];
  verdicts: Verdict[];
  hazards: string[];
  repeat_failure_window_days: number;
  /** Same-category reports within this many metres merge into one issue. */
  cluster_radius_m: number;
  /** A new issue this close to a Verified resolved one (same category) is a repeat failure. */
  repeat_failure_radius_m: number;
  /**
   * Max points per impact-score component, e.g.
   * `{unique_reporters: 35, severity: 30, context: 20, days_elapsed: 15}`.
   */
  score_weights?: Record<string, number>;
  wards: Ward[];
  demo_locations: DemoLocation[];
  limits?: Limits;
}

export interface CityStats {
  clusters: number;
  reports: number;
  unresolved: number;
  /** Open + in progress + pending verification + unverified closure. */
  active: number;
  closures: number;
  verified_closure_rate: number | null;
  unverified_closure_rate: number | null;
  sla_breached_open: number;
  repeat_failures: number;
  generated_at: string;
}

export interface WardRow {
  ward: string;
  /** Official ward number, when known (e.g. Bellandur = 150). */
  number: number | null;
  zone: string;
  lat: number;
  lng: number;
  total: number;
  reports: number;
  /** Open + in progress + pending verification + unverified closure. */
  active: number;
  open: number;
  in_progress: number;
  resolved_pending_verification: number;
  resolved_verified: number;
  closure_disputed: number;
  /** Issues that currently carry an official closure claim. */
  closures: number;
  verified_closure_rate: number | null;
  /** (Pending verification + unverified closure) / closures, in %. */
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

/** Issue summary embedded in a notification. */
export interface NotificationCluster {
  id: string;
  title: string;
  status: ClusterStatus;
  status_label: string;
  category_label: string;
  ward: string;
}

/** In-app message, e.g. "an official says this is fixed — send a fresh photo". */
export interface Notification {
  id: string;
  created_at: string;
  cluster_id: string;
  /** Reporter id the message is addressed to. */
  recipient: string;
  kind: 'verification_request' | string;
  channel: string;
  message: string;
  status: NotificationStatus;
  read_at: string | null;
  cluster: NotificationCluster | null;
}

export interface NotificationList {
  notifications: Notification[];
  unread: number;
}

export interface MarkReadResponse {
  updated: number;
  unread: number;
}

// -------------------------------------------------------------------- inputs --

export interface FormFile {
  blob: Blob;
  filename: string;
}

/**
 * What the ORIGINAL photo file's EXIF said, read on the client before the
 * resize/re-encode strips it (see lib/exif.ts). Sent as `photo_exif` ('1'/'0'),
 * `photo_lat` and `photo_lng`; omit all three when there is no photo.
 */
export interface PhotoExifInput {
  /** The original file carried EXIF metadata at all. */
  photo_exif?: boolean;
  /** GPS from the original photo's EXIF; the server treats it as the photo's location. */
  photo_lat?: number;
  photo_lng?: number;
}

export interface NewReportInput extends PhotoExifInput {
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
  /**
   * Where the citizen is. The server only attaches the corroboration within 250 m of
   * the issue (accuracy counts as slack), else 422 `too_far`; send the issue's own
   * coordinates when there is no usable fix (none, or accuracy > 1000 m).
   */
  lat: number;
  lng: number;
  accuracy?: number | null;
  reporter_id?: string;
  text?: string;
  photo?: FormFile;
}

export interface StatusUpdate {
  status: 'open' | 'in_progress';
  note?: string;
  actor?: string;
}

export interface ResolveInput extends PhotoExifInput {
  note?: string;
  actor?: string;
  after_photo?: FormFile;
  /**
   * Device position when the photo was taken. The server only uses it when the
   * photo itself has no EXIF GPS (`photo_lat`/`photo_lng` win). The UI sends it
   * only from touch devices (`(pointer: coarse)`) with a fix of ≤ 100 m: a desktop
   * demo reports a Wi-Fi/IP guess and would be flagged as the wrong spot.
   */
  lat?: number;
  lng?: number;
  accuracy?: number | null;
}

export interface VerifyInput extends PhotoExifInput {
  photo: FormFile;
  reporter_id?: string;
  note?: string;
  /** Device position when the photo was taken; see ResolveInput. */
  lat?: number;
  lng?: number;
  accuracy?: number | null;
}

export interface ExternalRefInput {
  /** Defaults to 'sahaaya' on the server. */
  system?: string;
  /** Official complaint number, 1-64 characters. */
  ref: string;
  actor?: string;
}

export interface EscalateInput {
  channel: EscalationChannel;
  requester_name?: string;
  /** Gemini draft (the server default, slower); `false` returns the template draft. */
  ai?: boolean;
}

export interface EscalationPackageInput {
  requester_name?: string;
}

export interface ClusterQuery {
  status?: ClusterStatus[];
  ward?: string;
  category?: string;
  /** Agency id or PRD code. */
  agency?: string;
  /** Only issues past their SLA target. */
  sla_breached?: boolean;
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

/**
 * Machine-readable `detail.code` of an API error, e.g. 'duplicate_submission',
 * 'audio_too_long' or 'not_civic_issue'; null when there is none.
 */
export function errorCode(e: unknown): string | null {
  if (!(e instanceof ApiError)) return null;
  const d = e.detail;
  return isRecord(d) && typeof d.code === 'string' ? d.code : null;
}

/** 429 detail: this reporter already filed the same category close by a few minutes ago. */
export interface DuplicateSubmission {
  code: 'duplicate_submission';
  message: string;
  duplicate_of: { report_id: string; cluster_id: string; created_at: string };
  retry_after_s: number;
}

/** Parses a 429 `duplicate_submission` error; null for any other error. */
export function duplicateSubmission(e: unknown): DuplicateSubmission | null {
  if (!(e instanceof ApiError) || e.status !== 429) return null;
  const d = e.detail;
  if (!isRecord(d) || d.code !== 'duplicate_submission') return null;
  const dup: Record<string, unknown> = isRecord(d.duplicate_of) ? d.duplicate_of : {};
  const str = (v: unknown): string => (typeof v === 'string' ? v : '');
  return {
    code: 'duplicate_submission',
    message: str(d.message) || e.message,
    duplicate_of: { report_id: str(dup.report_id), cluster_id: str(dup.cluster_id), created_at: str(dup.created_at) },
    retry_after_s: typeof d.retry_after_s === 'number' ? d.retry_after_s : 0,
  };
}

/** 422 detail: the device is too far from the issue to corroborate it. */
export interface TooFar {
  code: 'too_far';
  message: string;
  /** Metres between the device and the issue, when the server reports it. */
  distance_m: number | null;
  /** The allowed radius (250 m, accuracy counts as slack). */
  max_distance_m: number | null;
}

/** Parses a 422 `too_far` corroboration error; null for any other error. */
export function tooFar(e: unknown): TooFar | null {
  if (!(e instanceof ApiError) || e.status !== 422) return null;
  const d = e.detail;
  if (!isRecord(d) || d.code !== 'too_far') return null;
  const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  return {
    code: 'too_far',
    message: typeof d.message === 'string' && d.message ? d.message : e.message,
    distance_m: num(d.distance_m),
    max_distance_m: num(d.max_distance_m),
  };
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
    throw new ApiError(0, translate(getLang(), 'error.network'), e);
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

/** `photo_exif` ('1'/'0'), `photo_lat`, `photo_lng` form fields; unknown values are left out. */
function photoExifFields(input: PhotoExifInput): Record<string, FormValue> {
  return {
    photo_exif: input.photo_exif === undefined ? undefined : input.photo_exif ? '1' : '0',
    photo_lat: input.photo_lat,
    photo_lng: input.photo_lng,
  };
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
    if (q.sla_breached) params.set('sla_breached', 'true');
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
      ...photoExifFields(input),
    }),

  corroborate: (id: string, input: CorroborateInput) =>
    postForm<CorroborateResponse>(clusterPath(id, '/corroborate'), {
      lat: input.lat,
      lng: input.lng,
      accuracy: input.accuracy ?? undefined,
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
      ...photoExifFields(input),
      lat: input.lat,
      lng: input.lng,
      accuracy: input.accuracy ?? undefined,
    }),

  verify: (id: string, input: VerifyInput) =>
    postForm<ClusterDetailWithVerification>(clusterPath(id, '/verify'), {
      photo: input.photo,
      reporter_id: input.reporter_id,
      note: input.note,
      ...photoExifFields(input),
      lat: input.lat,
      lng: input.lng,
      accuracy: input.accuracy ?? undefined,
    }),

  /** One channel's draft; Gemini by default (slower), `ai: false` for the template. */
  escalate: (id: string, body: EscalateInput) => postJson<EscalationResponse>(clusterPath(id, '/escalate'), body),

  /** Instant template drafts (email, X, RTI) for one issue, plus a .txt bundle. */
  escalationPackage: (id: string, body: EscalationPackageInput = {}) => postJson<EscalationPackage>(clusterPath(id, '/escalation-package'), body),

  /** Package for a ward's Unverified closures and SLA-breached open issues; 409 `nothing_to_escalate` when there are none. */
  wardEscalationPackage: (ward: string, body: EscalationPackageInput = {}) =>
    postJson<EscalationPackage>(`/wards/${encodeURIComponent(ward)}/escalation-package`, body),

  /** Link the official grievance-portal complaint number (Sahaaya by default). */
  setExternalRef: (id: string, body: ExternalRefInput) => postJson<ClusterDetail>(clusterPath(id, '/external-ref'), body),

  notifications: (recipient: string, includeRead = false, limit = 50) => {
    const params = new URLSearchParams({ recipient, include_read: includeRead ? 'true' : 'false', limit: String(limit) });
    return request<NotificationList>(`/notifications?${params.toString()}`);
  },
  /** Omit `ids` to mark everything for this recipient as read. */
  markNotificationsRead: (recipient: string, ids?: string[]) => postJson<MarkReadResponse>('/notifications/read', ids ? { recipient, ids } : { recipient }),

  scorecard: () => request<Scorecard>('/wards/scorecard'),

  seed: (reset = true) => request<SeedSummary>(`/admin/seed?reset=${reset ? 'true' : 'false'}`, { method: 'POST' }),
  reset: () => request<{ status: string }>('/admin/reset', { method: 'POST' }),
};

export type Api = typeof api;
