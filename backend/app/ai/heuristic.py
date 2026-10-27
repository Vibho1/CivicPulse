"""Offline, deterministic evidence parser.

Used when ``GEMINI_API_KEY`` is not set and as a safety net if Gemini fails.
It cannot transcribe audio; it works from typed text (English, Hindi or
romanised/Kannada-script Kannada keywords) and the supplied context.
"""

from __future__ import annotations

import re

from ..domain import CATEGORY_LABELS, Category, Hazard
from ..schemas import EscalationDraft, EvidenceFlags, Extraction, VerificationResult
from . import templates
from .base import Media, ParseInput

CATEGORY_KEYWORDS: dict[Category, list[str]] = {
    Category.POTHOLE: ["pothole", "pot hole", "potholes", "gundi", "gundigalu", "ಗುಂಡಿ", "crater", "khadda", "gadda", "hole in the road"],
    Category.ROAD_DAMAGE: ["cave in", "cave-in", "road caved", "road sunk", "road broken", "road cut", "dug up", "trench", "uneven road", "ರಸ್ತೆ ಹಾಳ"],
    Category.FOOTPATH_DAMAGE: ["footpath", "pavement", "sidewalk", "slab broken", "ಫುಟ್‌ಪಾತ್"],
    Category.STREETLIGHT: ["streetlight", "street light", "street lamp", "light not working", "lights not working", "no light", "dark street", "beedi deepa", "deepa", "ದೀಪ", "high mast"],
    Category.GARBAGE: ["garbage", "kasa", "ಕಸ", "trash", "waste", "dump", "dumping", "black spot", "kachra", "litter", "stink", "smell"],
    Category.WATER_LEAK: ["water leak", "leaking", "leakage", "pipe burst", "pipeline burst", "neeru", "ನೀರು", "water flowing", "cauvery water", "paani"],
    Category.SEWAGE_OVERFLOW: ["sewage", "sewer", "ugd", "overflowing", "gutter", "nala", "ಒಳಚರಂಡಿ", "drainage overflow"],
    Category.OPEN_DRAIN_MANHOLE: ["manhole", "open drain", "drain cover", "missing cover", "charandi", "ಚರಂಡಿ", "open chamber"],
    Category.WATERLOGGING: ["waterlogging", "water logging", "waterlogged", "flooded", "flooding", "underpass", "stagnant water", "rain water", "ನೀರು ನಿಂತಿದೆ"],
    Category.FALLEN_TREE: ["tree fallen", "fallen tree", "tree fell", "branch", "mara biddide", "ಮರ"],
    Category.POWER_HAZARD: ["live wire", "wire hanging", "dangling wire", "electric shock", "transformer", "sparking", "sparks", "electric pole", "ವಿದ್ಯುತ್"],
    Category.TRAFFIC_SIGNAL: ["signal not working", "traffic signal", "traffic light", "zebra crossing", "signboard", "sign board"],
}

SEVERITY_PLUS_ONE = ["big", "huge", "large", "deep", "dodda", "ದೊಡ್ಡ", "dangerous", "danger", "urgent", "very", "tumba", "bahala", "bahut", "accident", "fell", "skid", "injur", "overflow", "blocked", "whole road", "entire"]
SEVERITY_PLUS_TWO = ["died", "death", "live wire", "shock", "fire", "child", "children", "ambulance", "school bus"]

HAZARD_KEYWORDS: dict[Hazard, list[str]] = {
    Hazard.NEAR_SCHOOL: ["school", "shaale", "ಶಾಲೆ", "college"],
    Hazard.NEAR_HOSPITAL: ["hospital", "clinic", "aspatre", "ಆಸ್ಪತ್ರೆ"],
    Hazard.TWO_WHEELER_SKID_RISK: ["two wheeler", "two-wheeler", "bike", "scooter", "skid", "fell down", "biddaru", "accident"],
    Hazard.NIGHT_VISIBILITY: ["night", "dark", "raatri", "ರಾತ್ರಿ", "not visible"],
    Hazard.WATERLOGGING: ["rain", "male", "ಮಳೆ", "water filled", "flooded", "waterlogg"],
    Hazard.JUNCTION: ["junction", "signal", "circle", "cross"],
    Hazard.BUS_STOP: ["bus stop", "bus stand"],
    Hazard.ARTERIAL_ROAD: ["main road", "ring road", "orr", "highway", "service road", "service lane", "100 ft", "100 feet", "80 feet"],
    Hazard.RECENT_DIGGING: ["dug", "digging", "trench", "pipeline work", "bwssb", "cable work", "bescom work", "metro work", "road cut"],
    Hazard.RECURRING: ["again", "repeat", "every year", "every monsoon", "re-opened", "reopened", "matte", "ಮತ್ತೆ"],
    Hazard.PEDESTRIAN_RISK: ["pedestrian", "walking", "footpath", "elderly", "children"],
    Hazard.BLOCKING_TRAFFIC: ["blocking", "blocked", "traffic jam", "jam"],
    Hazard.HEALTH_HAZARD: ["stink", "smell", "mosquito", "dengue", "sewage"],
    Hazard.LIVE_WIRE: ["live wire", "wire hanging", "dangling wire", "sparking"],
    Hazard.OPEN_DRAIN: ["open drain", "manhole", "open chamber"],
}

KANNADA_RE = re.compile(r"[\u0C80-\u0CFF]")
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
ROMAN_KANNADA = ["alli", "ide", "gundi", "dodda", "tumba", "bahala", "neeru", "kasa", "illa", "agide", "madi", "swalpa", "hatra", "yaake"]
LANDMARK_RE = re.compile(
    r"\b(?:near|opposite|opp\.?|beside|behind|next to|in front of|at|on)\s+([A-Za-z0-9][\w'’.\- ]{2,48}?)(?=\s+(?:alli|hatra|there|is|has|ide)\b|[,.;!?]|$)",
    re.IGNORECASE,
)


def _count_hits(text: str, words: list[str]) -> int:
    return sum(1 for w in words if w in text)


def detect_language(text: str) -> str:
    if KANNADA_RE.search(text):
        return "kn" if not re.search(r"[A-Za-z]{3,}", text) else "kn-en"
    if DEVANAGARI_RE.search(text):
        return "hi"
    if _count_hits(text.lower(), ROMAN_KANNADA) >= 1:
        return "kn-en"
    return "en"


def classify(text: str) -> tuple[Category, float]:
    t = text.lower()
    scores = {cat: _count_hits(t, words) for cat, words in CATEGORY_KEYWORDS.items()}
    best = max(scores, key=lambda c: scores[c])
    if scores[best] == 0:
        return Category.OTHER, 0.2
    return best, min(0.9, 0.5 + 0.15 * scores[best])


def severity_for(text: str, category: Category) -> int:
    t = text.lower()
    base = 3 if category in (Category.SEWAGE_OVERFLOW, Category.WATER_LEAK, Category.OPEN_DRAIN_MANHOLE, Category.POWER_HAZARD, Category.FALLEN_TREE) else 2
    sev = base + min(2, _count_hits(t, SEVERITY_PLUS_ONE)) + (2 if _count_hits(t, SEVERITY_PLUS_TWO) else 0)
    return max(1, min(5, sev))


def hazards_for(text: str, category: Category) -> list[Hazard]:
    t = text.lower()
    found = [h for h, words in HAZARD_KEYWORDS.items() if _count_hits(t, words)]
    if category == Category.POTHOLE and Hazard.WATERLOGGING in found and Hazard.TWO_WHEELER_SKID_RISK not in found:
        found.append(Hazard.TWO_WHEELER_SKID_RISK)
    if category == Category.STREETLIGHT and Hazard.NIGHT_VISIBILITY not in found:
        found.append(Hazard.NIGHT_VISIBILITY)
    if category in (Category.SEWAGE_OVERFLOW, Category.GARBAGE) and Hazard.HEALTH_HAZARD not in found:
        found.append(Hazard.HEALTH_HAZARD)
    if category == Category.POWER_HAZARD and Hazard.LIVE_WIRE not in found:
        found.append(Hazard.LIVE_WIRE)
    return found


def utility_type_for(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["bwssb", "water pipe", "pipeline", "cauvery"]):
        return "water_pipeline"
    if any(w in t for w in ["ugd", "sewage line", "sewer line"]):
        return "sewage"
    if any(w in t for w in ["bescom", "cable", "electric line", "power line"]):
        return "power_cable"
    if any(w in t for w in ["metro", "bmrcl", "namma metro"]):
        return "metro"
    if any(w in t for w in ["optical fibre", "optical fiber", "ofc", "telecom", "jio", "airtel"]):
        return "telecom"
    if any(w in t for w in ["gail", "gas pipeline", "gas line"]):
        return "gas"
    return "none"


def landmark_for(text: str) -> str | None:
    m = LANDMARK_RE.search(text)
    if not m:
        return None
    lm = m.group(1).strip(" .,-")
    return lm if len(lm) >= 3 else None


class HeuristicAI:
    name = "heuristic"

    def parse_report(self, inp: ParseInput) -> Extraction:
        text = (inp.text or "").strip()
        if not text and inp.audio is not None:
            text = ""
        category, conf = classify(text) if text else (Category.OTHER, 0.15)
        if category == Category.OTHER and inp.photo is not None and not text:
            # Photo-only report without Gemini: assume the most common issue type.
            category, conf = Category.POTHOLE, 0.2
        severity = severity_for(text, category) if text else 2
        hazards = hazards_for(text, category) if text else []
        if inp.context_hint:
            hint = inp.context_hint.lower()
            if "school" in hint and Hazard.NEAR_SCHOOL not in hazards:
                hazards.append(Hazard.NEAR_SCHOOL)
            if "hospital" in hint and Hazard.NEAR_HOSPITAL not in hazards:
                hazards.append(Hazard.NEAR_HOSPITAL)
            if "arterial" in hint and Hazard.ARTERIAL_ROAD not in hazards:
                hazards.append(Hazard.ARTERIAL_ROAD)
        landmark = landmark_for(text) if text else None
        utility = utility_type_for(text)
        recent_digging = Hazard.RECENT_DIGGING in hazards or utility != "none"
        label = CATEGORY_LABELS[category]
        title = f"{label} near {landmark}" if landmark else f"{label} in {inp.ward}"
        description = text if text else f"{label} reported via photo/voice at {inp.lat:.5f}, {inp.lng:.5f} (no transcript available offline)."
        transcript_note = "" if text or inp.audio is None else "[voice note received - transcription requires Gemini]"
        return Extraction(
            is_civic_issue=True,
            transcript=transcript_note if not text else "",
            transcript_english=text,
            language=detect_language(text) if text else "unknown",
            category=category,
            severity=severity,
            title=title[:120],
            description=description[:600],
            landmark=landmark,
            size_estimate=None,
            hazards=hazards,
            evidence=EvidenceFlags(
                recent_digging=recent_digging,
                utility_work_type=utility,  # type: ignore[arg-type]
                photo_provided=inp.photo is not None,
                photo_usable=inp.photo is not None,
                photo_matches_description=True,
                people_or_plates_visible=False,
            ),
            suggested_agency=None,
            agency_reasoning="Rule-based routing (offline mode).",
            confidence=conf,
        )

    def verify_fix(self, before: list[Media], after: Media, context: str) -> VerificationResult:
        return VerificationResult(
            same_location=False,
            same_location_confidence=0.0,
            issue_resolved=False,
            resolution_confidence=0.0,
            fix_quality="unknown",
            verdict="INCONCLUSIVE",  # type: ignore[arg-type]
            explanation=(
                "Automatic before/after comparison needs Gemini (set GEMINI_API_KEY). "
                "The after-photo has been stored; a citizen or ward committee member should confirm the fix."
            ),
            matched_cues=[],
            mismatch_cues=[],
        )

    def draft_escalation(self, channel: str, context: dict) -> EscalationDraft:
        return templates.draft(channel, context)
