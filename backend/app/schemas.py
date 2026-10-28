"""Pydantic schemas shared by the AI layer and the HTTP API.

The AI schemas (``Extraction``, ``VerificationResult``, ``EscalationDraft``)
double as Gemini structured-output schemas, so keep them JSON-schema friendly:
no dict fields, enums instead of free strings where it matters.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .domain import Agency, Category, ClusterStatus, Hazard, Verdict

# --------------------------------------------------------------------------- #
# AI: multimodal evidence parsing
# --------------------------------------------------------------------------- #


class EvidenceFlags(BaseModel):
    recent_digging: bool = Field(
        default=False,
        description=(
            "True if the photo or description shows a recently dug or refilled "
            "trench, pipeline/cable work, or utility road-cut at the spot."
        ),
    )
    utility_work_type: Literal[
        "water_pipeline", "sewage", "power_cable", "metro", "telecom", "gas", "unknown", "none"
    ] = Field(default="none", description="Type of utility work visible or described, if any.")
    photo_provided: bool = Field(default=False)
    photo_usable: bool = Field(
        default=False, description="Photo is clear enough to show the issue and its surroundings."
    )
    photo_matches_description: bool = Field(
        default=True, description="Photo content is consistent with what the citizen said."
    )
    people_or_plates_visible: bool = Field(
        default=False, description="Faces or vehicle number plates are readable in the photo."
    )
    stock_or_screenshot: bool = Field(
        default=False,
        description=(
            "Photo looks like a stock or downloaded image, a screenshot, a watermarked picture or a photo of a "
            "screen, rather than a fresh photo taken at the spot."
        ),
    )


class Dimensions(BaseModel):
    """PRD ``estimated_dimensions_cm``."""

    length: float | None = Field(default=None, description="Approximate length in centimetres.")
    width: float | None = Field(default=None, description="Approximate width in centimetres.")
    depth: float | None = Field(default=None, description="Approximate depth in centimetres.")


class SensitiveRegion(BaseModel):
    """A face or a readable number plate to blur before the photo is stored publicly."""

    kind: Literal["face", "license_plate"]
    box_2d: list[int] = Field(description="[ymin, xmin, ymax, xmax] normalised to 0-1000.")


class Extraction(BaseModel):
    is_civic_issue: bool = Field(description="False for spam, chatter or non-civic content.")
    transcript: str = Field(
        description=(
            "Verbatim transcript of the voice note in its original script "
            "(Kannada in Kannada script, English in Latin script, code-mixed as spoken). "
            "Empty string if there is no audio."
        )
    )
    transcript_english: str = Field(
        description="Faithful English translation of the transcript and typed text combined."
    )
    language: str = Field(
        description="BCP-47 style language of the voice note: 'kn', 'en', 'hi', 'kn-en' (code-mixed), etc."
    )
    category: Category
    severity: int = Field(description="1 = cosmetic, 3 = needs attention this week, 5 = immediate danger to life.")
    title: str = Field(description="Short English headline, e.g. 'Large pothole on ORR service lane near Ecospace'.")
    description: str = Field(description="One or two sentence English summary for an engineer.")
    landmark: str | None = Field(default=None, description="Nearest landmark or road mentioned or visible.")
    size_estimate: str | None = Field(
        default=None, description="Approximate size, e.g. '~1 m wide, 20 cm deep' or 'spans half the lane'."
    )
    estimated_dimensions_cm: Dimensions | None = Field(
        default=None, description="Approximate size of the defect in centimetres when it can be estimated; null otherwise."
    )
    hazards: list[Hazard] = Field(default_factory=list, description="Risk and context flags that apply.")
    evidence: EvidenceFlags = Field(default_factory=EvidenceFlags)
    suggested_agency: Agency | None = Field(
        default=None, description="Most likely owner agency given category, evidence and location."
    )
    agency_reasoning: str = Field(default="", description="One sentence explaining the agency choice.")
    confidence: float = Field(default=0.5, description="0-1 confidence in the overall extraction.")
    is_emergency: bool = Field(
        default=False,
        description=(
            "True only if someone is hurt or in immediate danger right now (fire, electrocution, a person injured "
            "or trapped, gas leak, collapse): the citizen must call 112."
        ),
    )
    sensitive_regions: list[SensitiveRegion] = Field(
        default_factory=list,
        description="Every human face and readable vehicle number plate in the PHOTO, for blurring. Empty if none.",
    )


# --------------------------------------------------------------------------- #
# AI: before/after verification
# --------------------------------------------------------------------------- #


class VerificationResult(BaseModel):
    same_location: bool = Field(description="AFTER photo shows the same spot as the BEFORE photo(s).")
    same_location_confidence: float = Field(description="0-1")
    issue_resolved: bool = Field(description="The reported issue is no longer present in the AFTER photo.")
    resolution_confidence: float = Field(description="0-1")
    fix_quality: Literal["proper", "partial", "cosmetic", "none", "unknown"] = Field(
        description=(
            "proper = durable repair (e.g. compacted asphalt flush with road); "
            "cosmetic = loose gravel/soil/debris covering the defect; none = not fixed."
        )
    )
    verdict: Verdict
    explanation: str = Field(description="2-3 sentences a ward engineer or RWA member can act on.")
    matched_cues: list[str] = Field(default_factory=list, description="Fixed features matching between photos.")
    mismatch_cues: list[str] = Field(default_factory=list, description="Features that do not match.")
    after_sensitive_regions: list[SensitiveRegion] = Field(
        default_factory=list, description="Every human face and readable number plate in the AFTER photo, for blurring."
    )


# --------------------------------------------------------------------------- #
# AI: escalation drafting
# --------------------------------------------------------------------------- #


class EscalationDraft(BaseModel):
    channel: Literal["email", "x", "rti"]
    subject: str | None = None
    to: str | None = None
    body: str


# --------------------------------------------------------------------------- #
# API payloads
# --------------------------------------------------------------------------- #


class StatusUpdate(BaseModel):
    status: Literal["open", "in_progress"]
    note: str | None = None
    actor: str | None = "official"


class EscalationRequest(BaseModel):
    channel: Literal["email", "x", "rti"] = "email"
    requester_name: str | None = None
    # False = instant deterministic template instead of a Gemini draft.
    ai: bool = True


class EscalationPackageRequest(BaseModel):
    """Email + X post + RTI in one go (deterministic templates, PRD: under 3 s)."""

    requester_name: str | None = None


class ExternalRefUpdate(BaseModel):
    """Ticket number from an official channel (assisted filing), e.g. a Sahaaya complaint."""

    system: str = Field(default="sahaaya", min_length=2, max_length=32)
    ref: str = Field(min_length=1, max_length=64)
    actor: str | None = None


class NotificationsRead(BaseModel):
    recipient: str = Field(min_length=1, max_length=128)
    ids: list[str] | None = Field(default=None, description="Omit to mark all of the recipient's notifications read.")


class ScoreComponent(BaseModel):
    component: str
    points: float
    reason: str


class ScoreBreakdown(BaseModel):
    total: float
    components: list[ScoreComponent]


class ClusterSummary(BaseModel):
    """Lightweight projection for map and lists."""

    id: str
    title: str
    category: Category
    status: ClusterStatus
    lat: float
    lng: float
    ward: str
    agency: Agency
    report_count: int
    max_severity: int
    impact_score: float
    sla_due_at: str
    sla_breached: bool
    repeat_failure: bool
    created_at: str
    updated_at: str
    primary_photo_url: str | None = None
    verification_verdict: Verdict | None = None
