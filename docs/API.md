# CivicPulse API (v0.1)

Base URL: `http://localhost:8000/api` (the backend also serves `/uploads/*` media and, when built, the PWA at `/`).
Interactive docs: `http://localhost:8000/docs`.

All responses are JSON. Timestamps are ISO-8601 UTC strings (`2026-10-27T12:34:56Z`).

## Vocabulary

| Field | Values |
|---|---|
| `category` | `pothole`, `road_damage`, `footpath_damage`, `streetlight`, `garbage`, `water_leak`, `sewage_overflow`, `open_drain_manhole`, `waterlogging`, `fallen_tree`, `power_hazard`, `traffic_signal`, `other` |
| `agency` | `GBA_ROADS`, `GBA_SWM`, `GBA_SWD`, `GBA_ELECTRICAL`, `GBA_FORESTRY`, `BWSSB`, `BESCOM`, `BMRCL`, `TRAFFIC_POLICE` |
| `status` | `open`, `in_progress`, `resolved_pending_verification`, `resolved_verified`, `closure_disputed` |
| `verdict` | `VERIFIED`, `UNVERIFIED_DIFFERENT_LOCATION`, `UNVERIFIED_NOT_FIXED`, `UNVERIFIED_COSMETIC`, `INCONCLUSIVE`, `NO_PROOF_PROVIDED` |

`GET /meta` returns labels, SLA hours, agency contact info, wards and demo locations for all of the above.

## Objects

### Cluster (returned by every cluster endpoint)
```json
{
  "id": "CP-7F3K2A", "title": "Large pothole on ORR service lane near Ecospace",
  "category": "pothole", "category_label": "Pothole",
  "status": "in_progress", "status_label": "In progress",
  "lat": 12.9262, "lng": 77.6816, "ward": "Bellandur", "zone": "Mahadevapura",
  "description": "...", "landmark": "Ecospace gate, Bellandur",
  "agency": "BWSSB", "agency_label": "BWSSB (Water Supply & Sewerage)", "agency_short": "BWSSB",
  "agency_reason": "Blue water pipe and fresh trench backfill visible ...",
  "agency_info": {"label": "...", "short": "...", "helpline": "1916", "x_handle": "@bwssb_official", "email_hint": "...", "scope": "..."},
  "report_count": 4, "max_severity": 5, "impact_score": 87.2,
  "score_breakdown": {"total": 87.2, "components": [{"component": "corroboration", "points": 23.2, "reason": "4 independent reports"}, ...]},
  "hazards": ["arterial_road", "two_wheeler_skid_risk", "night_visibility"],
  "context": [{"name": "Bellandur Gate / Ecospace", "type": "junction", "distance_m": 0}],
  "sla_hours": 72, "sla_due_at": "...", "sla_breached": true, "hours_open": 147.3, "hours_to_sla": -75.3,
  "repeat_failure": false, "previous_cluster_id": null,
  "created_at": "...", "updated_at": "...",
  "resolved_at": null, "resolved_by": null, "resolution_note": null, "closure_count": 0,
  "verification_verdict": null, "verified_at": null,
  "primary_photo_url": "/uploads/R-ABC123.jpg", "after_photo_url": null
}
```
Score components: `corroboration` (0-30), `severity` (0-30), `context` (0-20), `hazard` (0-15), `sla` (0-10), `repeat_failure` (0/10). Total capped at 100.

### Report
`id, cluster_id, created_at, lat, lng, accuracy, reporter_id, text, transcript, transcript_english, language, category, category_label, severity, title, description, landmark, size_estimate, hazards[], evidence{recent_digging, utility_work_type, photo_provided, photo_usable, photo_matches_description, people_or_plates_visible}, agency, agency_reason, ai_mode, confidence, ward, exif_gps, is_corroboration, photo_url, audio_url, extraction{...raw model output}`

### Verification
`id, cluster_id, created_at, kind ("official_closure" | "citizen"), actor, verdict, same_location, issue_resolved, fix_quality ("proper"|"partial"|"cosmetic"|"none"|"unknown"), same_location_confidence, resolution_confidence, explanation, ai_mode, note, photo_url, before_photo_urls[], details{matched_cues[], mismatch_cues[]}`

### Event (timeline)
`id, cluster_id, created_at, type, actor, note, payload{}` with `type` in `reported, merged, corroborated, reopened, status_changed, resolved, closure_check, citizen_verification, repeat_failure_flagged, escalation_drafted`.

## Endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | | `{status, ai_mode: "gemini"\|"heuristic", model, last_ai_error, counts, demo_mode}` |
| GET | `/meta` | | vocabularies, `wards[]`, `demo_locations[]` |
| GET | `/stats` | | city totals `{clusters, reports, unresolved, closures, verified_closure_rate, unverified_closure_rate, sla_breached_open, repeat_failures}` |
| POST | `/reports` | multipart: `lat`, `lng` (required), `accuracy?`, `text?`, `reporter_id?`, `language_hint?`, `audio?` (file), `photo?` (file). At least one of audio/photo/text. | `201 {report, cluster, merged, reopened, repeat_failure, previous_cluster, extraction, ai_mode, location_warning}`; `422 {detail: {message, extraction}}` if not a civic issue |
| GET | `/reports/{id}` | | `{report, cluster}` |
| GET | `/clusters` | query: `status` (comma list), `ward`, `category`, `agency`, `limit` | `{clusters: Cluster[]}` sorted by impact score |
| GET | `/clusters/{id}` | | `{cluster, reports[], verifications[], events[], previous_cluster}` |
| POST | `/clusters/{id}/corroborate` | multipart: `lat`, `lng`, `reporter_id?`, `text?`, `photo?` | `201 {cluster, merged, report}` - one-tap "I see this too" |
| POST | `/clusters/{id}/status` | JSON `{status: "open"\|"in_progress", note?, actor?}` | cluster detail; `409` on invalid transition |
| POST | `/clusters/{id}/resolve` | multipart: `note?`, `actor?`, `after_photo?` (file) | cluster detail + `verification`. Runs the AI closure check. |
| POST | `/clusters/{id}/verify` | multipart: `photo` (file, required), `reporter_id?`, `note?` | cluster detail + `verification`. Citizen proof photo. |
| POST | `/clusters/{id}/escalate` | JSON `{channel: "email"\|"x"\|"rti", requester_name?}` | `{draft: {channel, subject, to, body}, ai_mode, context}` |
| GET | `/wards/scorecard` | | `{city: {...}, wards: [{ward, zone, lat, lng, total, reports, open, in_progress, resolved_pending_verification, resolved_verified, closure_disputed, closures, verified_closure_rate, unverified_closure_rate, disputed_closure_rate, avg_hours_to_close, avg_hours_to_verified_fix, sla_breach_rate, sla_breached_open, repeat_failure_rate, avg_open_impact, top_agency}]}` |
| POST | `/admin/seed?reset=true` | | seeds the Bengaluru demo story (demo mode only) |
| POST | `/admin/reset` | | wipes all data (demo mode only) |

## Status machine

```
open ──official──▶ in_progress ──resolve──▶ AI closure check
  │                                            ├─ pass / no photo ─▶ resolved_pending_verification ──citizen photo VERIFIED──▶ resolved_verified
  │                                            └─ different spot / cosmetic / not fixed ─▶ closure_disputed
  └──────────── new report on a pending closure ─▶ closure_disputed (reopened by community)
A new report within 180 days of a *verified* fix at the same spot creates a new cluster flagged repeat_failure.
```
