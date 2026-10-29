# CivicPulse — Product Requirements Document (PRD)

| | |
|---|---|
| **Product** | CivicPulse — from complaint to closure, with proof |
| **Version** | 1.0 (MVP) |
| **Status** | Implemented; open questions tracked in §12 |
| **Geography** | Bengaluru (Greater Bengaluru Authority, ex-BBMP) |
| **Companion docs** | [TDD.md](TDD.md) · [WHATSAPP.md](WHATSAPP.md) |

---

## 1. Problem statement

Bengaluru does not lack complaint channels (Sahaaya, the pothole app, I Change My City, Fix My Street, X). Complaints still stall because:

1. **Fragmented ownership.** A pothole over a water-pipeline trench is BWSSB's, not the roads wing's; nobody tells the citizen, so the ticket ping-pongs or dies.
2. **Zero verification of closures.** An official marks "Resolved"; nobody checks whether the fix is real, at the right spot, or merely cosmetic.
3. **Repeat failures are invisible.** A patch that fails in 45 days is re-filed as a new complaint and paid for again, instead of being claimed under the contractor's defect-liability period.
4. **No public accountability signal.** Citizens, RWAs and the press cannot see the difference between *closed* and *actually fixed* per ward.

## 2. Product vision

> CivicPulse is a **civic accountability layer on top of** existing complaint channels — not another complaint box. It turns a 10-second voice note and a photo into a routed ticket, clusters and ranks issues by civic impact, **audits every closure with evidence**, tracks warranty failures, and publishes ward scorecards.

## 3. Goals and non-goals

### Goals
- **G1** Make reporting effortless in the citizen's own language (Kannada / English / Hindi / code-mixed), from the PWA or WhatsApp.
- **G2** Route each issue to the correct agency on the first attempt, with a stated reason.
- **G3** Rank issues by civic impact, not by complaint volume (de-duplicated by unique citizens).
- **G4** Make "Resolved" mean something: every closure is checked against photographic evidence and citizen confirmation.
- **G5** Surface repeat failures as warranty claims.
- **G6** Give citizens and RWAs one-click escalation (email, X, RTI) and public ward scorecards.
- **G7** Protect privacy and resist spam/abuse by design.

### Non-goals
- **NG1** Dispatching emergency services. Emergencies are redirected to **112**.
- **NG2** Replacing or filing directly into Sahaaya / agency portals (no public APIs exist). Filing is *assisted*; the official complaint number can be linked afterwards.
- **NG3** Adjudicating disputes. Verification is *evidence with confidence*, not a legal finding.
- **NG4** City-scale infrastructure in the MVP (see §10 Scale).

## 4. Users and personas

| Persona | Needs | Primary surfaces |
|---|---|---|
| **Citizen / commuter** (Kannada or English, mid-range Android) | Report in 10 s, see it got routed, be asked to confirm fixes near them | PWA `/report`, WhatsApp, in-app inbox |
| **RWA / ward committee member** | See ward state, escalate in bulk with evidence, cite RTI | `/scorecard`, ward escalation package |
| **Ward engineer / agency official** | Claim a fix with an after-photo, see what is pending in their ward | Official mode on issue page |
| **Journalist / civic researcher** | Export verified vs unverified closure rates per ward | `/scorecard`, API |

## 5. User journeys (MVP)

1. **Report** → citizen records voice + photo at location → sees ticket with category, severity, agency + reason, merged into an existing issue if one exists within 50 m.
2. **Corroborate** → citizen taps "I see this too" on a nearby issue (≤ 250 m) → issue's unique-reporter count and score rise.
3. **Official closure** → official marks Resolved with after-photo → system GPS-checks and AI-audits the photo → issue becomes *Pending verification* or *Unverified closure*.
4. **Citizen proof** → reporters and nearby citizens get a "send a proof photo" request → their photo verifies (or disputes) the closure.
5. **Repeat failure** → a new report at a verified-fixed spot inside 180 days is flagged and linked to the earlier ticket.
6. **Escalate** → one click produces email + X post + RTI drafts for an issue or a whole ward.
7. **Scorecard** → ward rows with verified/unverified closure rate, SLA breach rate, repeat-failure rate, accountability grade.

## 6. Functional requirements

Each requirement lists acceptance criteria (AC). IDs are stable for cross-reference from the TDD and tests.

### FR-1 Multilingual voice + photo intake
- **FR-1.1** Accept a voice note (≤ 30 s, ≤ 10 MB), a photo (JPEG/PNG/WebP, ≤ 10 MB) and/or typed text, plus device GPS. At least one of audio/photo/text is required.
- **FR-1.2** Transcribe Kannada, English, Hindi and code-mixed speech; produce an English translation.
- **FR-1.3** Emit a structured ticket: `category`, `severity` (low → critical), `estimated_dimensions_cm`, `extracted_landmark`, `hazards[]`, evidence flags, `confidence`.
- **FR-1.4** Categories: the seven core (`pothole`, `unrestored_utility_trench`, `streetlight_outage`, `garbage_dump`, `waterlogging`, `damaged_footpath`, `fallen_tree`) plus Bengaluru extensions (`road_damage`, `water_leak`, `sewage_overflow`, `open_drain_manhole`, `power_hazard`, `traffic_signal`, `other`).
- **FR-1.5** Reports that are not civic issues are rejected (`422 not_civic_issue`); unclassifiable reports (`other`, confidence < 0.3) are bounced with a prompt to describe the problem (`422 low_confidence`).
- **FR-1.6** Emergencies (someone hurt / immediate danger) are flagged and the UI shows a **Call 112** banner; the civic issue is still filed.
- **FR-1.7** WhatsApp Business (Cloud API) is an equivalent intake channel.
- **FR-1.8** The system works **offline** (no model key) with a heuristic text parser; accountability logic is unaffected.

### FR-2 Agency routing
- **FR-2.1** Every issue gets a primary agency, a one-line reason and a 0–1 routing confidence.
- **FR-2.2** Deterministic rules override defaults when evidence exists: fresh trench + water pipe → **BWSSB** (secondary GBA Roads); inside metro barricades → **BMRCL**; tree on live lines → secondary BESCOM; traffic blocked → secondary Traffic Police.
- **FR-2.3** Agency IDs are `GBA_*`, `BWSSB`, `BESCOM`, `BMRCL`, `TRAFFIC_POLICE`; legacy codes (`BBMP_ROADS`, `BTP`, …) are returned as aliases and accepted in filters.

### FR-3 Clustering and Civic Impact Score
- **FR-3.1** Same-category reports within **50 m** of an active issue merge into it; the pin is the running centroid.
- **FR-3.2** Score 0–100 with explained components: unique citizens **35**, severity **30**, context **20** (arterial road / junction; school, hospital, transit within 200 m), days elapsed **15** (clock stops on official closure).
- **FR-3.3** Re-reports by the same citizen never inflate the score.
- **FR-3.4** The same reporter filing the same category within **1 km / 5 min** is rejected as a duplicate (`429`).
- **FR-3.5** Each category carries an SLA (hours); breach state is computed and shown.

### FR-4 Proof-of-fix verification
- **FR-4.1** An official closure may attach an after-photo; its GPS (EXIF first, then original-file EXIF forwarded by the PWA, then device position) must be within **50 m** of the issue, else verdict `UNVERIFIED_DIFFERENT_LOCATION` with no model call.
- **FR-4.2** The after-photo is audited against up to two before-photos: same location? resolved? fix quality (proper / partial / cosmetic / none)?
- **FR-4.3** Verdicts: `VERIFIED`, `UNVERIFIED_DIFFERENT_LOCATION`, `UNVERIFIED_NOT_FIXED`, `UNVERIFIED_COSMETIC`, `INCONCLUSIVE`, `NO_PROOF_PROVIDED`; each has confidence and an explanation.
- **FR-4.4** On every closure, all reporters of the issue plus citizens active within **200 m** in the last **30 days** receive a proof-photo request (in-app inbox; optional webhook relay).
- **FR-4.5** Status becomes *Unverified closure* when the audit fails, a citizen proof photo shows a different spot, or a new report arrives against a pending closure.
- **FR-4.6** *Verified resolved* requires a citizen photo verdict of `VERIFIED`.

### FR-5 Repeat-failure tracking
- **FR-5.1** A new same-category report within **25 m** and **180 days** of a *Verified resolved* issue creates a new issue flagged `repeat_failure`, linked to `previous_cluster_id`.

### FR-6 Escalation packages
- **FR-6.1** Per issue: email to ward engineer (cc secondary agency), X post ≤ 280 chars tagging the agency, RTI application under Section 6(1), each citing cluster ids, coordinates, ISO timestamps, failure reason and before/after photo links.
- **FR-6.2** Per ward: bundles the ward's unverified closures and SLA-breached open issues, grouped by agency; `409 nothing_to_escalate` when empty.
- **FR-6.3** Templates render in < 3 s (actual: milliseconds); the model may optionally rewrite one channel, with template fallback if it drops required facts.
- **FR-6.4** When an official complaint number is linked (`external_ref`), drafts cite it.

### FR-7 Ward scorecards
- **FR-7.1** Per ward: active issues, verified vs unverified closure rate, SLA breach/compliance rate, time to close / to verified fix, repeat-failure rate, top agency, top problem.
- **FR-7.2** An **accountability index** (0–100) and grade A–F: 40 % verified-closure rate, 30 % SLA compliance, 15 % no repeat failures, 15 % no disputed closures; `low_data` below 3 closures.
- **FR-7.3** City funnel: reports → issues → closures → AI-checked → citizen-verified / awaiting proof / disputed.

### FR-8 Privacy and anti-spam
- **FR-8.1** Phone numbers masked in every response and draft.
- **FR-8.2** Faces and number plates blurred before storage (requires the model); photo metadata stripped by re-encoding.
- **FR-8.3** Citizens appear under stable pseudonyms; device ids are never returned.
- **FR-8.4** Voice notes private by default (`PUBLIC_AUDIO=false`).
- **FR-8.5** Photo provenance flags: `exif_stripped`, `exif_location_far` (> 500 m), `stock_or_screenshot`.
- **FR-8.6** Reporter credibility 0–1 = `(3 + confirmed) / (5 + confirmed + flagged + 2·rejected)`; shown, never used to hide reports or alter the score.

### FR-9 Bilingual UI
- **FR-9.1** One-tap English ⇄ ಕನ್ನಡ switch, remembered per device, `?lang=kn` deep links.
- **FR-9.2** Vocabulary (categories, statuses, agencies, verdicts, hazards, wards) translated by id; citizens' words and AI explanations shown verbatim. Dates `YYYY-MM-DD` IST.

### FR-10 Assisted filing into official systems
- **FR-10.1** `POST /clusters/{id}/external-ref` stores the official complaint number and system (e.g. Sahaaya); subsequent escalations cite it.

## 7. Issue lifecycle (product view)

| Status id | Label | Meaning |
|---|---|---|
| `open` | Open | Reported, no action |
| `in_progress` | In progress | Official acknowledged |
| `resolved_pending_verification` | Pending verification | Official closed; AI check passed or no photo given; awaiting citizen proof |
| `resolved_verified` | Verified resolved | Citizen photo confirmed the fix |
| `closure_disputed` | Unverified closure | AI, citizen photo or a new report contradicts the closure |

Transitions are detailed in [TDD.md §6](TDD.md#6-closure-state-machine).

## 8. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-1 | Intake latency | p95 < 5 s with the model; model parse timeout 15 s then heuristic fallback |
| NFR-2 | Escalation package latency | < 3 s (template path: ms) |
| NFR-3 | Availability without AI | 100 % of non-vision features work offline |
| NFR-4 | Privacy | No raw phone numbers, device ids or unblurred faces/plates in stored or served data |
| NFR-5 | Device support | Installable PWA on mid-range Android; camera + MediaRecorder + GPS |
| NFR-6 | Deployability | Single container; Cloud Run via Terraform; SQLite replicated to GCS |
| NFR-7 | Observability | `/health` exposes AI mode, model, last AI error, counts, feature flags |
| NFR-8 | Testability | Deterministic demo seed with no model calls; pytest suite covers every FR |

## 9. Success metrics

| Metric | Why it matters |
|---|---|
| **Unverified-closure rate** per ward and agency | The core accountability signal |
| **Verified-closure rate** | Fixes citizens actually confirmed |
| **Duplicates merged %** | Signal quality for agencies |
| **Repeat-failure rate** | Warranty leakage |
| **Proof-request response rate** | Citizen engagement in verification |
| **Time to verified fix** vs SLA | Real responsiveness |
| **Routing acceptance** (routing confidence, re-routes) | Ends ping-pong |

## 10. Scope, phasing and roadmap

**MVP (this release)** — FR-1 … FR-10 above, Bengaluru demo dataset, SQLite, single Cloud Run service.

**Next**
1. Contractor / defect-liability matching from tender data.
2. Official ward GeoJSON and numbers (OQ-2).
3. Coarse public locations for privacy.
4. Passive pothole detection from fleet accelerometers.
5. Monsoon waterlogging early warning.
6. RWA petition mode.
7. Push into Sahaaya once an API exists.

## 11. Known limitations (honest statement)

- Ward centroids and sensitive-zone points are approximate stand-ins for GBA GIS / OSM layers; only Bellandur carries its official ward number (150).
- SLA hours are configurable assumptions, not official charters.
- Agency handles and helplines are best-effort and must be verified before production.
- Demo photos are AI-generated.
- Face/plate blurring and photo audits need the model; the offline parser cannot do them.

## 12. Open questions

| ID | Question | Current stance |
|---|---|---|
| OQ-1 | Should credibility ever gate visibility? | No — displayed only (FR-8.6) |
| OQ-2 | Source of official ward boundaries and numbers | Pending GBA GeoJSON |
| OQ-3 | Which agency publishes defect-liability data for contractor matching? | Roadmap item |
| OQ-4 | Official SLA timelines per category | Configurable assumptions in `SLA_HOURS` |
| OQ-5 | Proof-request delivery channel at scale (WhatsApp templates vs SMS) | Webhook hook exists; bridge TBD |
| OQ-6 | Should coarse public locations be the default? | Roadmap |

## Appendix A — Reference demo script (3 minutes)

Seed first (`make seed` or **Demo → Seed** in the app). The AI status pill shows *Gemini live* when a key is set.

1. **Report in Kannada (FR-1, FR-2, FR-3).** On `/report`, pick the "ORR service lane, Bellandur" preset, record *"Outer Ring Road service lane alli Ecospace hatra dodda gundi ide"*, attach a pothole photo showing the blue pipeline trench. The ticket is routed to **BWSSB** with the reason ("fresh trench backfill / water pipe visible") and merges into the existing 4-report cluster — the impact score climbs.
2. **Clustering + score (FR-3).** Open the issue: reports in Kannada, English and Hindi; the score breakdown shows the PRD weights (unique citizens, critical severity, arterial road, days elapsed with "SLA breached by 3 days"); timeline and agency card with helpline, X handle and PRD code.
3. **Fake closure caught (FR-4).** Switch on **Official mode**, open the Koramangala pothole, "Mark resolved" with the wrong-spot photo (`backend/app/data/demo_photos/kor_pothole_after_wrong.jpg`) → **UNVERIFIED_DIFFERENT_LOCATION**, status *Unverified closure*. Repeat on Jayanagar with the gravel patch → **UNVERIFIED_COSMETIC**.
4. **Proof that it was fixed (FR-4.6).** On HSR Layout's garbage black spot, submit the citizen photo → **VERIFIED**; status *Verified resolved*.
5. **Repeat failure (FR-5).** The Agara junction pothole shows "Marked fixed 45 days ago — failed again", linked to its earlier ticket.
6. **Scorecard + escalation (FR-6, FR-7).** `/scorecard` shows unverified-closure rate, HSR's repeat-failure rate and per-ward SLA breaches. **Escalate** on the Bellandur row builds the *Ward 150 Bellandur* package (email, X post, RTI, `.txt` download). On the ORR issue, **Escalation package** does the same for one issue and **Rewrite with Gemini** redrafts one channel.
