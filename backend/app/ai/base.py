"""Provider-agnostic AI interface used by the services layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..schemas import EscalationDraft, Extraction, VerificationResult


@dataclass(frozen=True)
class Media:
    data: bytes
    mime_type: str
    label: str = ""


@dataclass(frozen=True)
class ParseInput:
    text: str | None
    audio: Media | None
    photo: Media | None
    lat: float
    lng: float
    ward: str
    context_hint: str = ""  # e.g. "near Sakra World Hospital (210 m); on Outer Ring Road"
    language_hint: str | None = None


class EvidenceAI(Protocol):
    """Everything CivicPulse needs from a multimodal model."""

    name: str

    def parse_report(self, inp: ParseInput) -> Extraction: ...

    def verify_fix(self, before: list[Media], after: Media, context: str) -> VerificationResult: ...

    def draft_escalation(self, channel: str, context: dict) -> EscalationDraft: ...
