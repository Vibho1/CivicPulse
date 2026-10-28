"""AI provider factory.

``get_ai()`` returns a :class:`ResilientAI` that prefers Gemini when a key is
configured (or Vertex AI is enabled) and always falls back to the offline heuristic
provider, so a demo never dies on a quota error or a flaky network.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from ..config import Settings, get_settings
from ..schemas import EscalationDraft, Extraction, VerificationResult
from .base import EvidenceAI, Media, ParseInput
from .heuristic import HeuristicAI

log = logging.getLogger(__name__)


class ResilientAI:
    def __init__(self, primary: EvidenceAI | None, fallback: EvidenceAI):
        self.primary = primary
        self.fallback = fallback
        self.last_error: str | None = None

    @property
    def mode(self) -> str:
        return self.primary.name if self.primary else self.fallback.name

    @property
    def model(self) -> str | None:
        return getattr(self.primary, "model", None)

    def parse(self, inp: ParseInput) -> tuple[Extraction, str]:
        if self.primary is not None:
            try:
                return self.primary.parse_report(inp), self.primary.name
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.exception("Primary AI parse failed; falling back to heuristic")
        return self.fallback.parse_report(inp), f"{self.fallback.name}_fallback" if self.primary else self.fallback.name

    def verify(self, before: list[Media], after: Media, context: str) -> tuple[VerificationResult, str]:
        if self.primary is not None:
            try:
                return self.primary.verify_fix(before, after, context), self.primary.name
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.exception("Primary AI verification failed; falling back to heuristic")
        return self.fallback.verify_fix(before, after, context), f"{self.fallback.name}_fallback" if self.primary else self.fallback.name

    def escalate(self, channel: str, context: dict) -> tuple[EscalationDraft, str]:
        if self.primary is not None:
            try:
                return self.primary.draft_escalation(channel, context), self.primary.name
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.exception("Primary AI escalation failed; falling back to templates")
        return self.fallback.draft_escalation(channel, context), f"{self.fallback.name}_fallback" if self.primary else self.fallback.name


def build_ai(
    api_key: str = "",
    model: str = "gemini-2.5-flash",
    timeout_s: int = 60,
    *,
    use_vertex: bool = False,
    project: str = "",
    location: str = "global",
    parse_timeout_s: int | None = None,
) -> ResilientAI:
    primary: EvidenceAI | None = None
    if api_key or use_vertex:
        try:
            from .gemini import GeminiAI

            primary = GeminiAI(
                api_key=api_key, model=model, timeout_s=timeout_s, vertex=use_vertex, project=project, location=location,
                parse_timeout_s=parse_timeout_s,
            )
            log.info("Gemini enabled (model=%s, via %s)", model, f"Vertex AI, location={location}" if use_vertex else "API key")
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not initialise Gemini (%s); running in heuristic mode", exc)
    else:
        log.warning("GEMINI_API_KEY not set - running in offline heuristic mode (no transcription / vision)")
    return ResilientAI(primary, HeuristicAI())


def build_ai_from_settings(s: Settings) -> ResilientAI:
    return build_ai(
        s.gemini_api_key,
        s.gemini_model,
        s.gemini_timeout_s,
        use_vertex=s.gemini_use_vertex,
        project=s.google_cloud_project,
        location=s.google_cloud_location,
        parse_timeout_s=s.gemini_parse_timeout_s,
    )


@lru_cache(maxsize=1)
def get_ai() -> ResilientAI:
    return build_ai_from_settings(get_settings())
