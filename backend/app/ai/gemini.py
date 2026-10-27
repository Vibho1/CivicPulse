"""Gemini-backed implementation of the EvidenceAI interface.

Uses the ``google-genai`` SDK with structured output (Pydantic schemas) so the
model returns validated JSON for every call.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..domain import Agency, Category, Hazard, Verdict
from ..schemas import EscalationDraft, Extraction, VerificationResult
from . import templates
from .audio import normalise_audio
from .base import Media, ParseInput

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

PARSER_SYSTEM_PROMPT = """You are the Civic Evidence Parser for CivicPulse, a civic-accountability platform for Bengaluru, India.

Citizens report problems with a short voice note (Kannada, English, Hindi, or code-mixed "Kanglish" such as
"ORR service lane alli dodda gundi ide"), optional typed text, and an optional photo taken at the spot.
Turn that into one structured ticket an engineer can act on.

Rules:
- transcript: transcribe the voice note verbatim in its original script (Kannada in Kannada script, English in Latin
  script, code-mixed exactly as spoken). Empty string if there is no audio.
- transcript_english: faithful English rendering of everything the citizen conveyed (voice + typed text).
- language: 'kn', 'en', 'hi', 'kn-en' (code-mixed), 'hi-en', etc.
- category: exactly one. 'pothole' for holes/craters in the carriageway; 'road_damage' for cave-ins, sunk patches,
  unrestored road cuts; 'open_drain_manhole' for missing covers; 'waterlogging' for standing/flood water.
- severity: 1 cosmetic, 2 minor, 3 needs attention this week, 4 likely to cause injury/damage, 5 immediate danger to life.
- hazards: only flags that are supported by the audio, text, photo, or the location context provided.
- evidence: look carefully at the photo for a freshly dug or refilled trench, pipeline/cable work, barricades or
  agency markings (BWSSB blue pipes, BESCOM cable ducts, BMRCL/Namma Metro barricades). Set photo_usable=false if the
  photo is blurry, dark, or does not show the issue.
- suggested_agency: GBA_ROADS (potholes, resurfacing, footpaths; the city corporation, formerly BBMP), GBA_SWM (garbage),
  GBA_SWD (storm-water drains / waterlogging), GBA_ELECTRICAL (streetlights), GBA_FORESTRY (trees), BWSSB (water supply,
  sewage, pipeline trenches), BESCOM (electric poles, wires, transformers, power-cable trenches), BMRCL (metro works),
  TRAFFIC_POLICE (signals, obstruction). If a pothole or road cut is clearly caused by a utility trench, route it to that
  utility agency (e.g. BWSSB) rather than roads, and say why in agency_reasoning.
- title: short English headline with the road/landmark, e.g. "Large pothole on ORR service lane near Ecospace".
- Never invent details that are not in the inputs. If the content is not a civic issue, set is_civic_issue=false and
  category='other'.
"""

VERIFIER_SYSTEM_PROMPT = """You are the closure-verification auditor for CivicPulse (Bengaluru civic issues).

You receive one or more BEFORE photos of a reported issue and one AFTER photo submitted as proof that it was fixed.
Decide, strictly from visual evidence:
1. same_location: do the photos show the same spot? Compare fixed features - buildings, compound walls, gates, poles,
   signboards, trees, kerbs, road markings, drain lines, manholes. Allow for different angle, zoom, lighting, time of
   day, weather and vehicles.
2. issue_resolved: is the reported defect actually gone?
3. fix_quality: 'proper' = durable repair (e.g. compacted hot-mix asphalt flush with the road, new cover, cleared
   area); 'partial' = improved but incomplete; 'cosmetic' = loose gravel/soil/debris or a token covering that will not
   last; 'none' = not fixed.
Verdict rules: different location -> UNVERIFIED_DIFFERENT_LOCATION; same location and not resolved ->
UNVERIFIED_NOT_FIXED; same location and cosmetic -> UNVERIFIED_COSMETIC; same location and proper/partial fix ->
VERIFIED; cannot tell -> INCONCLUSIVE. Be skeptical: officials sometimes upload a photo of a different, already-good
stretch. Write the explanation for a ward engineer or RWA member in 2-3 plain sentences.
"""

ESCALATION_SYSTEM_PROMPT = """You draft citizen escalations for CivicPulse (Bengaluru). Be factual, polite and firm.
Use only the facts in the provided JSON context; never invent names, dates or laws beyond the RTI Act, 2005.
- email: formal letter to the responsible ward/sub-division engineer; include ticket id, location, days open, number of
  independent reports, SLA status, verification status; ask for rectification within 48 hours, a geo-tagged after-photo
  on closure, and warranty/defect-liability enforcement if applicable. Provide a subject line.
- x: a single post of at most 280 characters, tagging the agency handle, with the ticket id and #CivicPulse.
- rti: an application under Section 6(1) of the RTI Act, 2005 to the Public Information Officer asking for the complaint
  registration date, responsible officer, work orders and bills for the stretch (last 3 years), contractor name and
  defect-liability period, and the inspection evidence used to close complaints.
"""


class GeminiAI:
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", timeout_s: int = 60):
        from google import genai
        from google.genai import types

        self._types = types
        self.model = model
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_s * 1000))

    # ------------------------------------------------------------------ utils
    def _config(self, system: str, schema: type[BaseModel], temperature: float, fast: bool):
        types = self._types
        kwargs: dict[str, Any] = dict(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=temperature,
            max_output_tokens=4096,
        )
        if fast and "2.5-flash" in self.model:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        return types.GenerateContentConfig(**kwargs)

    def _generate(self, parts: list, system: str, schema: type[T], temperature: float = 0.2, fast: bool = True) -> T:
        types = self._types
        content = types.Content(role="user", parts=parts)
        resp = self.client.models.generate_content(
            model=self.model, contents=[content], config=self._config(system, schema, temperature, fast)
        )
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, schema):
            return parsed
        text = resp.text or ""
        return schema.model_validate(_lenient(schema, json.loads(text)))

    def _part_bytes(self, media: Media):
        return self._types.Part.from_bytes(data=media.data, mime_type=media.mime_type)

    def _part_text(self, text: str):
        return self._types.Part.from_text(text=text)

    # ------------------------------------------------------------- interface
    def parse_report(self, inp: ParseInput) -> Extraction:
        parts = []
        if inp.audio is not None:
            audio = normalise_audio(inp.audio)
            parts.append(self._part_text("VOICE NOTE from the citizen:"))
            parts.append(self._part_bytes(audio))
        if inp.photo is not None:
            parts.append(self._part_text("PHOTO taken at the spot:"))
            parts.append(self._part_bytes(inp.photo))
        prompt = (
            f"GPS location: {inp.lat:.6f}, {inp.lng:.6f} (ward guess: {inp.ward}).\n"
            f"Location context: {inp.context_hint or 'none'}.\n"
            f"Typed text from the citizen: {inp.text.strip() if inp.text else '(none)'}\n"
            f"Language hint: {inp.language_hint or 'auto'}.\n"
            f"Inputs present: audio={'yes' if inp.audio else 'no'}, photo={'yes' if inp.photo else 'no'}.\n"
            "Produce the structured ticket."
        )
        parts.append(self._part_text(prompt))
        return self._generate(parts, PARSER_SYSTEM_PROMPT, Extraction, temperature=0.2, fast=True)

    def verify_fix(self, before: list[Media], after: Media, context: str) -> VerificationResult:
        parts = [self._part_text(f"Issue context: {context}")]
        for i, b in enumerate(before, 1):
            parts.append(self._part_text(f"BEFORE photo {i} (reported issue):"))
            parts.append(self._part_bytes(b))
        parts.append(self._part_text("AFTER photo (submitted as proof of repair):"))
        parts.append(self._part_bytes(after))
        parts.append(self._part_text("Audit the closure and return the structured verdict."))
        # Let the model think a little here: this is the accountability-critical call.
        return self._generate(parts, VERIFIER_SYSTEM_PROMPT, VerificationResult, temperature=0.1, fast=False)

    def draft_escalation(self, channel: str, context: dict) -> EscalationDraft:
        prompt = f"Channel: {channel}\nContext JSON:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
        try:
            draft = self._generate([self._part_text(prompt)], ESCALATION_SYSTEM_PROMPT, EscalationDraft, temperature=0.4, fast=True)
            draft.channel = channel  # type: ignore[assignment]
            return draft
        except Exception as exc:  # noqa: BLE001
            log.warning("Gemini escalation draft failed (%s); using template", exc)
            return templates.draft(channel, context)


# --------------------------------------------------------------------------- #
# Lenient coercion for when the SDK could not parse the structured response
# --------------------------------------------------------------------------- #


def _lenient(schema: type[BaseModel], data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    if schema is Extraction:
        valid_h = {h.value for h in Hazard}
        data["hazards"] = [h for h in (data.get("hazards") or []) if h in valid_h]
        if data.get("category") not in {c.value for c in Category}:
            data["category"] = Category.OTHER.value
        if data.get("suggested_agency") not in {a.value for a in Agency}:
            data["suggested_agency"] = None
        try:
            data["severity"] = max(1, min(5, int(round(float(data.get("severity", 3))))))
        except (TypeError, ValueError):
            data["severity"] = 3
        data.setdefault("evidence", {})
    if schema is VerificationResult and data.get("verdict") not in {v.value for v in Verdict}:
        data["verdict"] = Verdict.INCONCLUSIVE.value
    return data


def try_validate(schema: type[T], data: Any) -> T | None:
    try:
        return schema.model_validate(_lenient(schema, data))
    except ValidationError:
        return None
