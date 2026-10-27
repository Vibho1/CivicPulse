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
    hazards: list[Hazard] = Field(default_factory=list, description="Risk and context flags that apply.")
    evidence: EvidenceFlags = Field(default_factory=EvidenceFlags)
    suggested_agency: Agency | None = Field(
        default=None, description="Most likely owner agency given category, evidence and location."
    )
    agency_reasoning: str = Field(default="", description="One sentence explaining the agency choice.")
    confidence: float = Field(default=0.5, description="0-1 confidence in the overall extraction.")


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
