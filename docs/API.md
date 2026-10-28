# CivicPulse API (v0.2)

Base URL: `http://localhost:8000/api` (the backend also serves `/uploads/*` media and, when built, the PWA at `/`).
Interactive docs: `http://localhost:8000/docs`.

All responses are JSON (gzip-compressed above 1 KB when the client accepts it). Timestamps are ISO-8601 UTC strings (`2026-10-27T12:34:56Z`); the PWA shows dates as `YYYY-MM-DD` in IST.

## Vocabulary

| Field | Values |
|---|---|
| `category` | PRD enum: `pothole`, `unrestored_utility_trench`, `streetlight_outage`, `garbage_dump`, `waterlogging`, `damaged_footpath`, `fallen_tree`. Bengaluru extensions owned by the PRD's agencies: `road_damage`, `water_leak`, `sewage_overflow`, `open_drain_manhole`, `power_hazard`, `traffic_signal`, `other`. The old ids `streetlight`, `garbage`, `footpath_damage` are migrated in the database. |
| `agency` | `GBA_ROADS`, `GBA_SWM`, `GBA_SWD`, `GBA_ELECTRICAL`, `GBA_FORESTRY`, `BWSSB`, `BESCOM`, `BMRCL`, `TRAFFIC_POLICE` (GBA = Greater Bengaluru Authority, which replaced BBMP in 2025) |
| `agency_code` (PRD) | `BBMP_ROADS`, `BBMP_SWM`, `BBMP_SWD`, `BBMP_ELECTRICAL`, `BBMP_FORESTRY`, `BWSSB`, `BESCOM`, `BMRCL`, `BTP` - one per `agency`, in the same order |
| `status` | `open` "Open", `in_progress` "In progress", `resolved_pending_verification` "Pending verification", `resolved_verified` "Verified resolved", `closure_disputed` "Unverified closure" |
| `verdict` | `VERIFIED`, `UNVERIFIED_DIFFERENT_LOCATION`, `UNVERIFIED_NOT_FIXED`, `UNVERIFIED_COSMETIC`, `INCONCLUSIVE`, `NO_PROOF_PROVIDED` |
| `severity_level` | `low` (1-2), `medium` (3), `high` (4), `critical` (5) - derived from the 1-5 `severity` |
| `repair_quality` | `verified_complete`, `temporary_or_partial`, `unrepaired`, `mismatched_location`, or `null` when undecided - derived from `verdict` + `fix_quality` |
| `photo_flags` | `exif_stripped` (the original file had no camera metadata: forwarded, downloaded or stock?), `exif_location_far` (the photo's own GPS is more than 500 m from the pin), `stock_or_screenshot` (the model thinks it is a stock image or screenshot), `faces_or_plates_blurred` |

`GET /meta` returns:
- `categories[]` items `{id, label, sla_hours, prd}`.
- `agencies[]` items: contact info plus the PRD `code`.
- `statuses[]`, `verdicts[]`, `hazards[]`.
- `wards[]` items `{name, zone, lat, lng, number}`. `number` is set only for Bellandur (150) until the official ward GeoJSON lands (PRD OQ-2).
- `demo_locations[]`.
- `score_weights`, `cluster_radius_m` (50), `repeat_failure_radius_m` (25), `repeat_failure_window_days` (180), `emergency_number` ("112").
- The intake `limits`.

## Privacy (applies to every response)

- **Phone numbers are masked** as `98******10`. This covers every free-text field: text, transcripts, descriptions, notes, model output and escalation drafts.
- **Citizens appear under a stable pseudonym** (`citizen-1a2b3c`) in `reporter_id` and `actor`. Device ids are never returned, because they would let anyone read that citizen's inbox.
- **Voice notes are private by default.** `audio_url` is only included in the reporter's own `POST /reports` response, unless the server sets `PUBLIC_AUDIO=true`. Audio files get unguessable names.
- **Faces and number plates are blurred** before a photo is stored, when the model finds them. The report then gets the `faces_or_plates_blurred` flag, and `privacy_blurred` counts the blurred regions. This needs Gemini: the offline parser cannot detect faces or plates.
- **Photo metadata is stripped**: all photos are re-encoded.

## Objects

### Cluster (returned by every cluster endpoint)
```json
{
  "id": "CP-7F3K2A", "title": "Large pothole on ORR service lane near Ecospace",
  "category": "pothole", "category_label": "Pothole",
  "status": "in_progress", "status_label": "In progress",
  "lat": 12.9262, "lng": 77.6816, "ward": "Bellandur", "zone": "Mahadevapura",
  "description": "...", "landmark": "Ecospace gate, Bellandur",
  "agency": "BWSSB", "agency_code": "BWSSB", "agency_label": "BWSSB (Water Supply & Sewerage)", "agency_short": "BWSSB",
  "agency_reason": "Road cut from water-pipeline work: BWSSB must restore its trench ...",
  "agency_info": {"label": "...", "short": "...", "code": "BWSSB", "helpline": "1916", "x_handle": "@bwssb_official", "email_hint": "...", "scope": "..."},
  "secondary_agency": "GBA_ROADS", "secondary_agency_code": "BBMP_ROADS",
  "secondary_agency_label": "GBA Roads & Infrastructure (ex-BBMP)", "secondary_agency_short": "GBA Roads",
  "secondary_agency_reason": "GBA Roads signs off final resurfacing once BWSSB restores its road cut (road-cut permit condition).",
  "secondary_agency_info": {"label": "...", "helpline": "1533", "...": "..."},
  "routing_confidence": 0.93,
  "report_count": 4, "reporter_count": 4, "max_severity": 5, "severity_level": "critical", "impact_score": 66.6,
  "score_breakdown": {"total": 66.6, "components": [{"component": "unique_reporters", "points": 23.5, "reason": "4 independent citizens"}, ...]},
  "hazards": ["arterial_road", "two_wheeler_skid_risk", "night_visibility"],
  "context": [{"name": "Bellandur Gate / Ecospace", "type": "junction", "distance_m": 0}],
  "sla_hours": 72, "sla_due_at": "...", "sla_breached": true, "hours_open": 147.3, "hours_to_sla": -75.3,
  "repeat_failure": false, "previous_cluster_id": null,
  "created_at": "...", "updated_at": "...",
  "resolved_at": null, "resolved_by": null, "resolution_note": null, "closure_count": 0,
  "verification_verdict": null, "verified_at": null,
  "external_system": "sahaaya", "external_ref": "SAH-2026-0042", "external_ref_at": "...",
  "primary_photo_url": "/uploads/R-ABC123.jpg", "after_photo_url": null
}
```

**Impact score.** The score uses the PRD weights; the total is the sum of four components (0-100). `meta.score_weights` carries the weights.

| `component` | max | meaning |
|---|---|---|
| `unique_reporters` | 35 | Independent citizens, log-scaled; 10 or more earns full marks. One person re-reporting counts once. |
| `severity` | 30 | Worst report: low 7.5, medium 15, high 22.5, critical 30. |
| `context` | 20 | Road hierarchy: arterial road 10, or busy junction 5. Within 200 m: school 5, hospital 5, one transit hub (bus stand or metro) 4. |
| `days_elapsed` | 15 | Days since the first report, linear to full marks at 30 days. The clock stops when an official claims a fix. |

Hazard flags (live wire, open drain, ...) do not add points. They still drive severity, routing and the escalation text. Repeat failures are flagged separately.

Routing: `agency` is the primary owner; `secondary_agency` (nullable) shares responsibility - e.g. GBA Roads resurfacing after a BWSSB/BESCOM/BMRCL road cut, BESCOM for a tree on live lines, Traffic Police when traffic is blocked. `routing_confidence` (0-1) = rule strength x category certainty, +0.05 when the model's suggested agency agrees, -0.1 when it disagrees.

### Report
Fields: `id, cluster_id, created_at, lat, lng, accuracy, reporter_id (pseudonym), text, transcript, transcript_english, language, category, category_label, severity, severity_level, title, description, landmark, size_estimate, hazards[], evidence{recent_digging, utility_work_type, photo_provided, photo_usable, photo_matches_description, people_or_plates_visible, stock_or_screenshot}, agency, agency_code, agency_reason, secondary_agency, secondary_agency_reason, routing_confidence, ai_mode, confidence, ward, exif_gps, photo_flags[], privacy_blurred, reporter_credibility, is_corroboration, photo_url, audio_url, extraction{...raw model output}, parsed{...}`.

`parsed` is the PRD's parser output shape:
```json
{"category": "pothole", "severity": "high", "estimated_dimensions_cm": {"length": 120, "width": 80, "depth": 15},
 "extracted_landmark": "Outer Ring Road service lane", "transcription": "...", "language": "kn-en"}
```
`estimated_dimensions_cm` is `null` when the model gives no size; any of its three values may be `null`.

`reporter_credibility` (0-1, `null` for anonymous reports) is a track-record score: `(3 + confirmed) / (5 + confirmed + flagged + 2 x rejected)`.
- `confirmed`: reports that another citizen independently backed, or whose fix was verified.
- `flagged`: reports whose photo looked like a stock image or screenshot, or was taken far from the pin.
- `rejected`: submissions bounced as not a civic issue or unreadable.

The score is shown next to reports. It never hides a report and never changes the impact score.

### Verification
`id, cluster_id, created_at, kind ("official_closure" | "citizen"), actor (pseudonym for citizens), verdict, same_location, issue_resolved, fix_quality ("proper"|"partial"|"cosmetic"|"none"|"unknown"), repair_quality, same_location_confidence, resolution_confidence, location_match, gps_distance_m, gps_source ("exif"|"device"|null), explanation, verification_summary (= explanation), ai_mode, note, photo_url, before_photo_urls[], details{matched_cues[], mismatch_cues[]}`

The GPS proof check works as follows:
- **Which position counts.** The photo's GPS must be within **50 m** of the issue. EXIF GPS in the uploaded file is used first. Next comes `photo_lat`/`photo_lng`, the original file's EXIF GPS (read by the PWA before it resizes the photo). Last comes the optional device `lat`/`lng`/`accuracy`.
- **Too far away.** A photo taken farther than 50 m is `UNVERIFIED_DIFFERENT_LOCATION` (`ai_mode: "rule"`, no model call).
- **Different-location verdicts reopen the issue.** An official closure with such a photo becomes `closure_disputed`. So does a citizen proof photo that shows a different spot (PRD AC-4).
- **`location_match`.** It is true when vision and GPS agree it is the same spot, or when GPS alone places it there and vision was inconclusive.
- **Blurring.** Proof photos are face/plate-blurred like report photos.

### Event (timeline)
`id, cluster_id, created_at, type, actor, note, payload{}` with `type` in `reported, merged, corroborated, reopened, status_changed, resolved, closure_check, verification_requested, citizen_verification, repeat_failure_flagged, emergency_flagged, escalation_drafted, external_ref_recorded`.

### Notification (in-app inbox)
`id, created_at, cluster_id, recipient, kind ("verification_request"), channel ("in_app"), message, status ("unread"|"read"|"expired"), read_at, payload{verdict, reason: "reporter"|"nearby"}, cluster{id, title, status, status_label, category_label, ward}`

When an official resolves a cluster, these citizens get a "send a proof photo" request (`verification_requested` event):
- every reporter of that cluster;
- citizens who reported anything within 200 m in the last 30 days.

The request is also POSTed to `NOTIFY_WEBHOOK_URL` (e.g. a WhatsApp/SMS bridge) when that is set. Requests are marked `read` when the citizen submits a proof photo or re-reports. They become `expired` when the issue is verified, the closure is withdrawn, or a new closure supersedes them.

### Escalation package
Returned by `POST /clusters/{id}/escalation-package` and `POST /wards/{ward}/escalation-package`. It is built from templates in milliseconds (PRD: under 3 s), with no model call.
```json
{
  "scope": "cluster", "ward": "Bellandur", "ward_number": 150,
  "title": "...", "cluster_ids": ["CP-ABC123"],
  "clusters": [{"id": "CP-ABC123", "title": "...", "status": "closure_disputed", "status_label": "Unverified closure",
                "agency": "BESCOM", "agency_code": "BESCOM", "agency_label": "...",
                "failure_reason": "...", "sla_breached": true, "url": "https://.../clusters/CP-ABC123"}],
  "drafts": {"email": {"channel": "email", "subject": "...", "to": "...", "body": "..."},
             "x": {"channel": "x", "subject": null, "to": null, "body": "..."},
             "rti": {"channel": "rti", "subject": "...", "to": "...", "body": "..."}},
  "text": "all three drafts, ready to save as .txt",
  "filename": "civicpulse-escalation-CP-ABC123-2026-10-28.txt",
  "generated_at": "2026-10-28T09:00:00Z", "elapsed_ms": 12, "ai_mode": "template"
}
```
What every draft contains:
- the cluster id(s) and the ward (as "Ward 150 Bellandur" when the number is known);
- the responsible agency with its PRD code;
- the failure reason, coordinates and ISO timestamps;
- before/after photo links and the CivicPulse issue link, both as absolute URLs (`PUBLIC_BASE_URL`, else the request's host).

Channel rules:
- **X posts** are always 280 characters or fewer, and keep the cluster id.
- **RTI applications** cite Section 6(1) of the RTI Act 2005.
- **Linked official tickets.** When one is linked, the drafts cite it (`external_ref`).

The ward package groups the drafts by agency. It covers the ward's Unverified closures plus its SLA-breached open issues.

## Endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | | `{status, ai_mode: "gemini"\|"heuristic", model, last_ai_error, counts, demo_mode, features{whatsapp, public_audio, face_blur}}` |
| GET | `/meta` | | vocabularies (above), `wards[]`, `demo_locations[]`, `score_weights`, radii, `emergency_number`, `limits{max_image_mb, max_audio_mb, max_audio_s, duplicate_window_s, duplicate_radius_m, verify_gps_radius_m, corroborate_max_m}` |
| GET | `/stats` | | city totals `{clusters, active, reports, unresolved, closures, verified_closure_rate, unverified_closure_rate, sla_breached_open, repeat_failures, generated_at}` |
| POST | `/reports` | multipart: `lat`, `lng` (required), `accuracy?`, `text?`, `reporter_id?`, `language_hint?`, `photo_exif?` (`"1"`/`"0"`: did the original photo file carry EXIF), `photo_lat?`, `photo_lng?` (the original photo's EXIF GPS), `audio?` (file), `photo?` (file). At least one of audio/photo/text. | `201 {report, cluster, merged, reopened, repeat_failure, previous_cluster, extraction, ai_mode, location_warning, emergency}`. Errors below. |
| GET | `/reports/{id}` | | `{report, cluster}` |
| GET | `/clusters` | query: `status` (comma list), `ward`, `category`, `agency` (id or PRD code, e.g. `BBMP_ROADS`), `sla_breached` (`true`/`false`), `limit` | `{clusters: Cluster[]}` sorted by impact score |
| GET | `/clusters/{id}` | | `{cluster, reports[], verifications[], events[], previous_cluster}` |
| POST | `/clusters/{id}/corroborate` | multipart: `lat`, `lng`, `accuracy?`, `reporter_id?`, `text?`, `photo?` | `201 {cluster, merged, report}` - one-tap "I see this too". See note 1. |
| POST | `/clusters/{id}/status` | JSON `{status: "open"\|"in_progress", note?, actor?}` | cluster detail; `409` on invalid transition |
| POST | `/clusters/{id}/resolve` | multipart: `note?`, `actor?`, `after_photo?` (file), `photo_exif?`, `photo_lat?`, `photo_lng?`, `lat?`, `lng?`, `accuracy?` (device position, used only when the photo has no GPS) | cluster detail + `verification`. Runs the GPS + AI closure check and sends proof requests. |
| POST | `/clusters/{id}/verify` | multipart: `photo` (file, required), `reporter_id?`, `note?`, `photo_exif?`, `photo_lat?`, `photo_lng?`, `lat?`, `lng?`, `accuracy?` | cluster detail + `verification`. Citizen proof photo. |
| POST | `/clusters/{id}/escalate` | JSON `{channel: "email"\|"x"\|"rti", requester_name?, ai?: boolean}` | `{draft: {channel, subject, to, body}, ai_mode, context}`. See note 2. |
| POST | `/clusters/{id}/escalation-package` | JSON `{requester_name?}` | Escalation package (above), `scope: "cluster"` |
| POST | `/clusters/{id}/external-ref` | JSON `{system?: "sahaaya", ref, actor?}` | cluster detail. Links the complaint number from an official channel (assisted filing). |
| GET | `/notifications` | query: `recipient` (reporter id, required), `include_read?`, `limit?` | `{notifications: Notification[], unread}` |
| POST | `/notifications/read` | JSON `{recipient, ids?}` (omit `ids` = all) | `{updated, unread}` |
| GET | `/wards/scorecard` | | `{city: {...same as /stats}, wards: [...]}`. Row fields are listed in note 3. |
| POST | `/wards/{ward}/escalation-package` | JSON `{requester_name?}`; `{ward}` = name or number (`Bellandur` or `150`) | Escalation package, `scope: "ward"`. `404` unknown ward. `409 {code: "nothing_to_escalate", message}` when the ward has no Unverified closures or SLA-breached issues. |
| GET | `/whatsapp/webhook` | query: `hub.mode`, `hub.verify_token`, `hub.challenge` | Meta's subscription handshake (echoes the challenge). See note 4. |
| POST | `/whatsapp/webhook` | Meta WhatsApp Cloud API payload | `200` at once; messages are processed in the background. See note 4. |
| POST | `/admin/seed?reset=true` | | seeds the Bengaluru demo story (demo mode only) |
| POST | `/admin/reset` | | wipes all data (demo mode only) |

Endpoint notes:

1. **Corroborate ("I see this too").** The report attaches to the tapped issue only if the citizen is within 250 m of it. Device accuracy counts as slack, capped at 250 m. The new report is pinned to the issue's own location. Errors:
   - `422 too_far`: the citizen is farther than that.
   - `409`: the issue is already verified as fixed.
   - `429`: duplicate submission (see the errors table).
2. **Escalate.** `ai` defaults to `true`: a Gemini draft, which is slower. If that draft drops the cluster id or the issue link, or an X post runs over 280 characters, the template is used instead. `ai: false` returns the template draft at once. Email drafts cc the secondary agency.
3. **Ward scorecard rows.** Each row has: `ward, number, zone, lat, lng, total, active, reports, open, in_progress, resolved_pending_verification, resolved_verified, closure_disputed, closures, verified_closure_rate, unverified_closure_rate, disputed_closure_rate, avg_hours_to_close, avg_hours_to_verified_fix, sla_breach_rate, sla_compliance_rate, sla_breached_open, repeat_failure_rate, avg_open_impact, top_agency, accountability_index, grade, low_data, index_breakdown, top_problem, rank`.
   - `accountability_index` (0–100) = 40% verified-closure rate (neutral 50 when the ward has no closures) + 30% SLA compliance + 15% no repeat failures + 15% no disputed closures; `grade` A ≥ 85, B ≥ 70, C ≥ 55, D ≥ 40, else F; `low_data` is true below 3 closures; `index_breakdown[]` = `{component, weight, value, points, reason}`.
   - `rank`: 1 = worst index in the city (rows are returned worst first). `top_problem` = `{cluster_id, title, kind, status, category, agency, report_count, impact_score, sla_breached, hours_overdue, verification_verdict, previous_cluster_id}` or `null`; `kind` ∈ `disputed | repeat_failure | overdue | open | awaiting_proof` in that priority order, highest impact score first within a kind.
   - `city` additionally carries `funnel` = `{reports, issues, duplicates_merged_pct, closed, ai_checked, no_proof, citizen_verified, awaiting_proof, disputed, unverified_closure_rate}`, `grade_distribution` (`{A,B,C,D,F}` counts) and `median_index`.
   - `closures`: clusters an official has claimed fixed (`resolved_at` set), even if later reopened.
   - `unverified_closure_rate`: (closures − verified) / closures.
   - `active`: open + in progress + pending verification + unverified closure.
4. **WhatsApp webhook.** Both endpoints return `404` unless `WHATSAPP_VERIFY_TOKEN` is set. POST bodies are checked against `X-Hub-Signature-256` when `WHATSAPP_APP_SECRET` is set (`401` if invalid). Bodies are capped at 1 MB. See [WHATSAPP.md](WHATSAPP.md).

### Intake limits and errors

| Status | When | `detail` |
|---|---|---|
| `413` | photo > 10 MB or voice note > 10 MB (`MAX_IMAGE_MB`, `MAX_AUDIO_MB`) | string |
| `415` | photo is not JPEG, PNG or WebP | string |
| `422` | voice note longer than 30 s (`MAX_AUDIO_S`; browser WebM without a duration header is measured from packet timestamps) | `{code: "audio_too_long", message, max_audio_s}` |
| `422` | not a civic issue | `{code: "not_civic_issue", message, extraction}` |
| `422` | the parser cannot tell what the problem is (category `other` with confidence < 0.3) - the citizen is asked to describe it or add a clearer photo | `{code: "low_confidence", message, extraction}` |
| `422` | "I see this too" from farther than 250 m | `{code: "too_far", message, distance_m, max_distance_m}` |
| `429` | same `reporter_id` already filed the **same category within 1 km in the last 5 min** (`DUPLICATE_RADIUS_M`, `DUPLICATE_WINDOW_S`; `0` disables). Also applies to corroborations. Header `Retry-After`. | `{code: "duplicate_submission", message, duplicate_of: {report_id, cluster_id, created_at}, retry_after_s}` |

Bounced submissions (`not_civic_issue`, `low_confidence`) count against the reporter's credibility.

Emergencies: the parser flags a report as an emergency when someone is hurt or in immediate danger right now (fire, electrocution, a person injured or trapped, gas leak, collapse). Gemini makes this call; offline, a keyword check does. The `201` response then carries `emergency: {is_emergency: true, number: "112", message}`, and the issue gets an `emergency_flagged` event. CivicPulse files the civic issue but does not dispatch emergency services (PRD non-goal); the PWA shows a "Call 112" banner. Otherwise `emergency` is `null`.

## Status machine

```
open ──official──▶ in_progress ──resolve──▶ GPS check (> 50 m away ─▶ closure_disputed)
  │                                            └─ AI closure check
  │                                                 ├─ pass / no photo ─▶ resolved_pending_verification ──citizen photo VERIFIED──▶ resolved_verified
  │                                                 │                                                  └─citizen photo of another spot──▶ closure_disputed
  │                                                 └─ different spot / cosmetic / not fixed ─▶ closure_disputed
  └──────────── new report on a pending closure ─▶ closure_disputed (reopened by community)
Every resolve asks the issue's reporters (and citizens within 200 m) for a proof photo.
Reports of the same category within 50 m of an active cluster merge into it.
A new report within 25 m and 180 days of a *verified* fix of the same category creates a new cluster flagged repeat_failure.
```

## PRD field mapping

The API now uses the PRD's category ids and status labels. Two choices differ from the PRD:
- **Agency ids.** They stay `GBA_*`, because GBA is the current name of the ex-BBMP corporation. Every agency field has a PRD `*_code` alias.
- **Severity scale.** It stays 1-5, with `severity_level` giving the PRD's word.

| PRD term | API field |
|---|---|
| `BBMP_ROADS` / `BBMP_SWM` / `BBMP_ELECTRICAL` / `BTP` | `agency_code` / `secondary_agency_code` (ids `GBA_ROADS` / `GBA_SWM` / `GBA_ELECTRICAL` / `TRAFFIC_POLICE`, plus `GBA_SWD`, `GBA_FORESTRY`); `?agency=` accepts either |
| category enum (incl. `unrestored_utility_trench`) | `category` (same ids; seven extensions beyond the PRD enum, `meta.categories[].prd = false`) |
| parser output `{category, severity, estimated_dimensions_cm, extracted_landmark, transcription, language}` | `report.parsed` (also `severity_level`, `size_estimate`, `landmark`, `transcript` + `transcript_english`) |
| `routing_rationale`, confidence, secondary owner | `agency_reason`, `routing_confidence`, `secondary_agency` + `secondary_agency_reason` |
| `reporter_count`, `civic_impact_score` | `reporter_count`, `impact_score` (+ `score_breakdown` with the PRD components) |
| `location_match`, `repair_quality`, `verification_summary` | `location_match`, `repair_quality`, `verification_summary` |
| status `Pending Verification` / `Verified Resolved` / `Unverified Closure` | `status_label` of `resolved_pending_verification` / `resolved_verified` / `closure_disputed` |
| `is_repeat_failure` | `repeat_failure` (+ `previous_cluster_id`) |
| `official_ticket_id` | `external_ref` (+ `external_system`) |
| reporter credibility | `report.reporter_credibility` |
| EXIF-stripped / stock photo flags | `report.photo_flags` |
