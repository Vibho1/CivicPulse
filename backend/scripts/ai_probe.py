#!/usr/bin/env python3
"""Probe the live Gemini pipeline with the bundled demo photos.

Usage (from backend/, with GEMINI_API_KEY in .env or the environment):
    python -m scripts.ai_probe            # parse + verify + escalate
    python -m scripts.ai_probe --parse    # only the evidence parser
    python -m scripts.ai_probe --verify   # only the before/after audit

Exits non-zero if Gemini is not configured or a call fails, so it doubles as a
pre-demo health check.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai import build_ai_from_settings  # noqa: E402
from app.ai.base import Media, ParseInput  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.demo_photos import photo_bytes  # noqa: E402

PHOTOS = Path(__file__).resolve().parent.parent / "app" / "data" / "demo_photos"


def _photo(name: str) -> Media:
    return Media(photo_bytes(name), "image/jpeg", name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--escalate", action="store_true")
    ap.add_argument("--audio", help="Optional audio file (webm/m4a/mp3/wav) to transcribe along with the parse")
    args = ap.parse_args()
    run_all = not (args.parse or args.verify or args.escalate)

    s = get_settings()
    ai = build_ai_from_settings(s)
    if ai.primary is None:
        print("Gemini is not configured: set GEMINI_API_KEY (or GEMINI_USE_VERTEX=true with ADC) in .env and retry.")
        return 2
    print(f"Gemini model: {ai.model}")

    if run_all or args.parse:
        audio = None
        if args.audio:
            p = Path(args.audio)
            mime = {"webm": "audio/webm", "m4a": "audio/mp4", "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "flac": "audio/flac"}.get(p.suffix.lstrip("."), "audio/webm")
            audio = Media(p.read_bytes(), mime, p.name)
        t0 = time.time()
        extraction, mode = ai.parse(
            ParseInput(
                text=None if audio else "ORR service lane alli Ecospace hatra dodda gundi ide, BWSSB pipeline work aada mele haage bittidare",
                audio=audio,
                photo=_photo("orr_pothole_1"),
                lat=12.9262,
                lng=77.6816,
                ward="Bellandur",
                context_hint="junction: Bellandur Gate / Ecospace (0 m); arterial road: Outer Ring Road (0 m)",
                language_hint=None,
            )
        )
        print(f"\n== parse ({mode}, {time.time() - t0:.1f}s)")
        print(json.dumps(extraction.model_dump(mode="json"), indent=2, ensure_ascii=False))
        if mode != "gemini":
            print("Parse fell back to heuristic:", ai.last_error)
            return 1

    if run_all or args.verify:
        for label, before, after in [
            ("Koramangala: wrong-spot photo (expect UNVERIFIED_DIFFERENT_LOCATION)", "kor_pothole_before", "kor_pothole_after_wrong"),
            ("Jayanagar: gravel patch (expect UNVERIFIED_COSMETIC)", "jay_pothole_before", "jay_pothole_after_cosmetic"),
            ("HSR garbage: cleaned (expect VERIFIED)", "hsr_garbage_before", "hsr_garbage_after"),
        ]:
            t0 = time.time()
            result, mode = ai.verify([_photo(before)], _photo(after), label)
            print(f"\n== verify: {label} ({mode}, {time.time() - t0:.1f}s)")
            print(f"   verdict={result.verdict} same_location={result.same_location} ({result.same_location_confidence:.2f}) "
                  f"resolved={result.issue_resolved} ({result.resolution_confidence:.2f}) quality={result.fix_quality}")
            print(f"   {result.explanation}")
            if mode != "gemini":
                print("Verification fell back:", ai.last_error)
                return 1

    if run_all or args.escalate:
        ctx = {
            "cluster_id": "CP-DEMO01", "title": "Large pothole on ORR service lane near Ecospace", "category_label": "Pothole",
            "description": "Deep pothole at the edge of an unrestored BWSSB trench.", "location_text": "12.92620, 77.68160",
            "landmark": "Ecospace gate", "ward": "Bellandur", "zone": "Mahadevapura", "agency": "BWSSB",
            "agency_label": "BWSSB (Water Supply & Sewerage)", "agency_email_hint": "Sub-division AEE", "agency_x_handle": "@bwssb_official",
            "agency_helpline": "1916", "agency_reason": "pipeline trench", "created_at": "2026-10-21", "days_open": 6, "report_count": 4,
            "max_severity": 5, "impact_score": 87.2, "sla_hours": 72, "sla_breached": True, "status": "in_progress", "status_label": "In progress",
            "verification_summary": "No closure attempted yet.", "repeat_failure": False, "previous_cluster_id": None, "requester_name": "Bellandur RWA",
        }
        for channel in ("email", "x", "rti"):
            t0 = time.time()
            draft, mode = ai.escalate(channel, ctx)
            print(f"\n== escalate {channel} ({mode}, {time.time() - t0:.1f}s)")
            if draft.subject:
                print("Subject:", draft.subject)
            print(draft.body[:600] + ("..." if len(draft.body) > 600 else ""))

    print("\nAI probe OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
