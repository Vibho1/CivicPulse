"""Demo scenario seeder.

Seeds a realistic Bengaluru dataset without calling Gemini (extractions and
verification verdicts are pre-computed, exactly as the model would return
them), so the dashboard tells the full story even offline:

* ORR service-lane pothole: 4 reports in 3 languages, routed to BWSSB
  because of a visible pipeline trench, SLA breached, in progress.
* Koramangala: official closed it with a photo of a different spot ->
  closure disputed by the AI check.
* Jayanagar: cosmetic gravel patch -> closure disputed.
* HSR Layout: a verified fix that failed again -> repeat failure flagged.
* Verified closures, pending closures, and a no-proof closure for the
  ward scorecard.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from .ai import ResilientAI
from .ai.base import Media
from .ai.heuristic import HeuristicAI
from .demo_photos import have_real_photos, photo_bytes
from .domain import Agency, Category, ClusterStatus, Hazard, Verdict
from .schemas import EvidenceFlags, Extraction, VerificationResult
from .services import closure
from .services.common import now_utc, to_iso
from .services.intake import ingest, refresh_scores
from .store import Store

H = Hazard
C = Category
A = Agency


def _ex(**kw) -> Extraction:
    base = dict(
        is_civic_issue=True,
        transcript="",
        transcript_english="",
        language="en",
        category=C.POTHOLE,
        severity=3,
        title="",
        description="",
        landmark=None,
        size_estimate=None,
        hazards=[],
        evidence=EvidenceFlags(photo_provided=True, photo_usable=True),
        suggested_agency=None,
        agency_reasoning="",
        confidence=0.85,
    )
    base.update(kw)
    if not base["transcript_english"]:
        base["transcript_english"] = base["description"]
    return Extraction(**base)


def _verdict(verdict: Verdict, explanation: str, *, same: bool, fixed: bool, quality: str, matched=None, mismatch=None) -> VerificationResult:
    return VerificationResult(
        same_location=same,
        same_location_confidence=0.93 if same else 0.12,
        issue_resolved=fixed,
        resolution_confidence=0.9 if fixed else 0.15,
        fix_quality=quality,  # type: ignore[arg-type]
        verdict=verdict,
        explanation=explanation,
        matched_cues=matched or [],
        mismatch_cues=mismatch or [],
    )


def seed_demo(store: Store, uploads_dir: Path, reset: bool = True) -> dict:
    if reset:
        store.reset()
    ai = ResilientAI(None, HeuristicAI())  # never spend model calls while seeding
    now = now_utc()

    def ts(days: float = 0, hours: float = 0) -> str:
        return to_iso(now - timedelta(days=days, hours=hours))

    def photo(name: str | None) -> Media | None:
        return Media(photo_bytes(name), "image/jpeg", name) if name else None

    def report(lat, lng, extraction, when, photo_name=None, reporter=None, text=None):
        return ingest(
            store, ai, lat=lat, lng=lng, uploads_dir=uploads_dir, text=text, photo=photo(photo_name),
            reporter_id=reporter, extraction_override=extraction, ai_mode_override="gemini (seeded)", created_at=when,
        )

    created: list[str] = []

    # ------------------------------------------------------------------ 1. ORR
    r = report(
        12.92620, 77.68160,
        _ex(
            transcript="ORR service lane alli Ecospace hatra dodda gundi ide, BWSSB pipeline work aada mele haage bittidare.",
            transcript_english="There is a big pothole on the ORR service lane near Ecospace; after the BWSSB pipeline work they just left it like this.",
            language="kn-en", category=C.POTHOLE, severity=4,
            title="Large pothole on ORR service lane near Ecospace",
            description="Deep pothole (~1 m) at the edge of a recently refilled BWSSB pipeline trench on the Outer Ring Road service lane near the Ecospace gate.",
            landmark="Ecospace gate, Bellandur", size_estimate="~1 m wide, 25 cm deep",
            hazards=[H.ARTERIAL_ROAD, H.TWO_WHEELER_SKID_RISK, H.RECENT_DIGGING],
            evidence=EvidenceFlags(recent_digging=True, utility_work_type="water_pipeline", photo_provided=True, photo_usable=True),
            suggested_agency=A.BWSSB, agency_reasoning="Blue water pipe and fresh trench backfill visible at the pothole edge: an unrestored BWSSB road cut.",
            confidence=0.92,
        ),
        ts(days=6, hours=3), "orr_pothole_1", "citizen-ravi",
    )
    orr = r.cluster["id"]
    created.append(orr)
    report(12.92628, 77.68152, _ex(
        transcript="Huge pothole on the service road just before the Ecospace gate, two-wheelers are skidding on it at night.",
        language="en", category=C.POTHOLE, severity=4, title="Large pothole on ORR service lane near Ecospace",
        description="Two-wheelers skidding at night on a large pothole just before the Ecospace gate.", landmark="Ecospace gate",
        hazards=[H.NIGHT_VISIBILITY, H.TWO_WHEELER_SKID_RISK, H.ARTERIAL_ROAD],
        evidence=EvidenceFlags(recent_digging=True, utility_work_type="water_pipeline", photo_provided=True, photo_usable=True), confidence=0.88,
    ), ts(days=5, hours=1), "orr_pothole_2", "citizen-meera")
    report(12.92615, 77.68166, _ex(
        transcript="ಎಕೋಸ್ಪೇಸ್ ಹತ್ತಿರ ಸರ್ವಿಸ್ ರಸ್ತೆಯಲ್ಲಿ ದೊಡ್ಡ ಗುಂಡಿ ಇದೆ, ಮಳೆ ಬಂದಾಗ ನೀರು ತುಂಬಿಕೊಂಡು ಕಾಣಿಸುವುದೇ ಇಲ್ಲ.",
        transcript_english="There is a big pothole on the service road near Ecospace; when it rains it fills with water and you cannot see it at all.",
        language="kn", category=C.POTHOLE, severity=4, title="Large pothole on ORR service lane near Ecospace",
        description="Pothole fills with water during rain and becomes invisible to riders.", landmark="Ecospace",
        hazards=[H.WATERLOGGING, H.TWO_WHEELER_SKID_RISK, H.ARTERIAL_ROAD],
        evidence=EvidenceFlags(recent_digging=True, utility_work_type="water_pipeline", photo_provided=True, photo_usable=True), confidence=0.9,
    ), ts(days=3, hours=6), "orr_pothole_3", "citizen-lakshmi")
    closure.set_status(store, store.get_cluster(orr), ClusterStatus.IN_PROGRESS, "Forwarded to BWSSB sub-division for trench restoration.", "ward-engineer-bellandur", ts(days=2, hours=4))
    report(12.92624, 77.68158, _ex(
        transcript="Ecospace ke paas service lane mein bahut bada gaddha hai, kal raat ek scooter wala gir gaya.",
        transcript_english="There is a very big pothole in the service lane near Ecospace; last night a scooter rider fell.",
        language="hi-en", category=C.POTHOLE, severity=5, title="Large pothole on ORR service lane near Ecospace",
        description="A scooter rider fell at the pothole last night; immediate hazard.", landmark="Ecospace",
        hazards=[H.TWO_WHEELER_SKID_RISK, H.ARTERIAL_ROAD, H.NIGHT_VISIBILITY],
        evidence=EvidenceFlags(recent_digging=True, utility_work_type="water_pipeline", photo_provided=True, photo_usable=True), confidence=0.9,
    ), ts(days=1, hours=2), "orr_pothole_4", "citizen-arjun")

    # ------------------------------------------------- 2. Koramangala fake closure
    r = report(12.93520, 77.62600, _ex(
        transcript="Koramangala 5th block 17th main alli, green gate iro mane munde pothole ide.",
        transcript_english="In Koramangala 5th Block 17th Main, there is a pothole in front of the house with the green gate.",
        language="kn-en", category=C.POTHOLE, severity=3, title="Pothole on 17th Main, Koramangala 5th Block",
        description="Medium pothole in front of a white compound wall with a green gate, next to a whitewashed tree trunk.",
        landmark="17th Main, Koramangala 5th Block", size_estimate="~60 cm wide",
        hazards=[H.TWO_WHEELER_SKID_RISK, H.NEAR_SCHOOL], confidence=0.86,
    ), ts(days=9, hours=5), "kor_pothole_before", "citizen-divya")
    kor = r.cluster["id"]
    created.append(kor)
    report(12.93526, 77.62594, _ex(
        transcript="Pothole near the green gate house on 17th main, my car hit it hard this morning.",
        language="en", category=C.POTHOLE, severity=3, title="Pothole on 17th Main, Koramangala 5th Block",
        description="Car hit the pothole near the green gate house.", landmark="17th Main, Koramangala 5th Block",
        hazards=[H.TWO_WHEELER_SKID_RISK], confidence=0.84,
    ), ts(days=8, hours=2), None, "citizen-sanjay")
    closure.resolve(
        store, ai, store.get_cluster(kor), uploads_dir=uploads_dir, after_photo=photo("kor_pothole_after_wrong"),
        note="Pothole filled on 17th Main.", actor="ward-engineer-koramangala", ts=ts(days=2, hours=1),
        result_override=_verdict(
            Verdict.UNVERIFIED_DIFFERENT_LOCATION,
            "The after-photo shows a smooth road in front of a yellow building with a blue shutter; the before-photo has a white compound wall, a green gate and a whitewashed tree trunk. None of these fixed features appear in the after-photo, so it is a different stretch. The reported pothole has not been shown as repaired.",
            same=False, fixed=False, quality="unknown", mismatch=["white compound wall missing", "green gate missing", "tree at kerb missing", "building colour differs"],
        ),
    )

    # ------------------------------------------------- 3. Indiranagar streetlight
    created.append(report(12.97190, 77.64120, _ex(
        transcript="100 feet road alli CMH road junction hatra street light 4 days inda off ide, raatri tumba dark.",
        transcript_english="On 100 Feet Road near the CMH Road junction the streetlight has been off for 4 days; it is very dark at night.",
        language="kn-en", category=C.STREETLIGHT, severity=3, title="Streetlight out on 100 Ft Road near CMH Road junction",
        description="Streetlight pole dark for several nights on a busy commercial stretch.", landmark="CMH Road junction, Indiranagar",
        hazards=[H.NIGHT_VISIBILITY, H.PEDESTRIAN_RISK, H.ARTERIAL_ROAD], confidence=0.87,
    ), ts(days=4, hours=7), "ind_streetlight", "citizen-farah").cluster["id"])

    # ------------------------------------------------- 4. HSR garbage: verified closure
    r = report(12.91160, 77.63890, _ex(
        transcript="27th main 14th cross corner alli garbage black spot agide, naayigalu ellaa haradtive.",
        transcript_english="The 27th Main and 14th Cross corner has become a garbage black spot; dogs are scattering it everywhere.",
        language="kn-en", category=C.GARBAGE, severity=3, title="Garbage black spot at 27th Main / 14th Cross, HSR Layout",
        description="Heap of mixed waste bags at the street corner next to a grey compound wall with a no-dumping sign.",
        landmark="27th Main & 14th Cross, HSR Layout", hazards=[H.HEALTH_HAZARD], confidence=0.9,
    ), ts(days=8, hours=4), "hsr_garbage_before", "citizen-nikhil")
    hsr_g = r.cluster["id"]
    created.append(hsr_g)
    report(12.91166, 77.63884, _ex(transcript="Garbage dumped again at the 27th main corner, stinks badly.", language="en", category=C.GARBAGE, severity=3,
                                      title="Garbage black spot at 27th Main / 14th Cross, HSR Layout", description="Garbage dumped again; strong smell.",
                                      landmark="27th Main, HSR Layout", hazards=[H.HEALTH_HAZARD], confidence=0.85), ts(days=7, hours=9), None, "citizen-pooja")
    report(12.91155, 77.63896, _ex(transcript="Black spot at 27th main corner, kids walk past this to school.", language="en", category=C.GARBAGE, severity=3,
                                      title="Garbage black spot at 27th Main / 14th Cross, HSR Layout", description="Children walk past the dump on the way to school.",
                                      landmark="27th Main, HSR Layout", hazards=[H.HEALTH_HAZARD, H.NEAR_SCHOOL], confidence=0.85), ts(days=7, hours=2), None, "citizen-ahmed")
    closure.resolve(store, ai, store.get_cluster(hsr_g), uploads_dir=uploads_dir, after_photo=photo("hsr_garbage_after"), note="Spot cleared and sanitised; bins placed.",
                    actor="swm-jhi-hsr", ts=ts(days=5, hours=3),
                    result_override=_verdict(Verdict.VERIFIED, "Same corner: the grey compound wall and faded no-dumping sign line up. The waste heap is gone and the pavement is swept; this is a proper clean-up.", same=True, fixed=True, quality="proper", matched=["grey compound wall", "no-dumping sign", "kerb line"]))
    closure.citizen_verify(store, ai, store.get_cluster(hsr_g), uploads_dir=uploads_dir, photo=photo("hsr_garbage_citizen"), reporter_id="citizen-nikhil", note="Still clean today.",
                           ts=ts(days=4, hours=2),
                           result_override=_verdict(Verdict.VERIFIED, "Citizen photo from a different angle shows the same wall and sign with no waste present a day later. Fix confirmed.", same=True, fixed=True, quality="proper", matched=["compound wall", "sign"]))

    # ------------------------------------------------- 5. HSR Agara: verified fix that failed again
    r = report(12.92190, 77.64750, _ex(
        transcript="Agara junction signal hatra dodda gundi, bus stop munde.", transcript_english="Big pothole near the Agara junction signal, in front of the bus stop.",
        language="kn-en", category=C.POTHOLE, severity=4, title="Pothole at Agara junction near bus stop",
        description="Large pothole at the Agara junction signal in front of the bus shelter.", landmark="Agara junction, HSR Layout",
        hazards=[H.JUNCTION, H.BUS_STOP, H.ARTERIAL_ROAD, H.TWO_WHEELER_SKID_RISK], confidence=0.9,
    ), ts(days=50, hours=2), "hsr_pothole_old_before", "citizen-raghav")
    agara_old = r.cluster["id"]
    created.append(agara_old)
    report(12.92196, 77.64744, _ex(transcript="Pothole at Agara signal, buses swerving.", language="en", category=C.POTHOLE, severity=4, title="Pothole at Agara junction near bus stop",
                                      description="Buses swerving around the pothole at Agara signal.", landmark="Agara junction", hazards=[H.JUNCTION, H.BUS_STOP], confidence=0.85), ts(days=49, hours=5), None, "citizen-uma")
    closure.resolve(store, ai, store.get_cluster(agara_old), uploads_dir=uploads_dir, after_photo=photo("hsr_pothole_old_after"), note="Hot-mix patch laid.", actor="ward-engineer-hsr", ts=ts(days=45, hours=4),
                    result_override=_verdict(Verdict.VERIFIED, "Same junction: signal pole and bus shelter match. The pothole is filled with compacted black asphalt flush with the road surface.", same=True, fixed=True, quality="proper", matched=["signal pole", "bus shelter", "lane markings"]))
    closure.citizen_verify(store, ai, store.get_cluster(agara_old), uploads_dir=uploads_dir, photo=photo("hsr_pothole_old_after"), reporter_id="citizen-raghav", note=None, ts=ts(days=44, hours=1),
                           result_override=_verdict(Verdict.VERIFIED, "Citizen confirms the asphalt patch at the same junction; surface is level.", same=True, fixed=True, quality="proper", matched=["signal pole", "bus shelter"]))
    r = report(12.92192, 77.64752, _ex(
        transcript="Agara signal hatra adhe gundi matte open agide, patch ella hogide male alli.", transcript_english="The same pothole near the Agara signal has opened up again; the patch washed away in the rain.",
        language="kn-en", category=C.POTHOLE, severity=4, title="Pothole at Agara junction has reopened",
        description="The asphalt patch at Agara junction has broken up again after the rains, exposing the same pothole in front of the bus shelter.",
        landmark="Agara junction, HSR Layout", hazards=[H.JUNCTION, H.BUS_STOP, H.ARTERIAL_ROAD, H.RECURRING, H.WATERLOGGING, H.TWO_WHEELER_SKID_RISK], confidence=0.9,
    ), ts(days=2, hours=3), "hsr_pothole_repeat", "citizen-raghav")
    agara_new = r.cluster["id"]
    created.append(agara_new)

    # ------------------------------------------------- 6. Jayanagar cosmetic patch
    r = report(12.93080, 77.58380, _ex(
        transcript="4th block 30th cross alli red brick wall munde pothole, tumba deep.", transcript_english="On 30th Cross, 4th Block, in front of the red brick wall there is a very deep pothole.",
        language="kn-en", category=C.POTHOLE, severity=3, title="Deep pothole on 30th Cross, Jayanagar 4th Block",
        description="Deep pothole on a tree-lined residential street in front of a red-brick compound wall.", landmark="30th Cross, Jayanagar 4th Block",
        hazards=[H.TWO_WHEELER_SKID_RISK, H.PEDESTRIAN_RISK], confidence=0.88,
    ), ts(days=6, hours=6), "jay_pothole_before", "citizen-sheela")
    jay = r.cluster["id"]
    created.append(jay)
    report(12.93086, 77.58374, _ex(transcript="Pothole opposite the red brick wall on 30th cross, scooters wobble here daily.", language="en", category=C.POTHOLE, severity=3,
                                      title="Deep pothole on 30th Cross, Jayanagar 4th Block", description="Scooters wobble on the pothole daily.", landmark="30th Cross, Jayanagar", hazards=[H.TWO_WHEELER_SKID_RISK], confidence=0.84), ts(days=5, hours=3), None, "citizen-kiran")
    closure.resolve(store, ai, store.get_cluster(jay), uploads_dir=uploads_dir, after_photo=photo("jay_pothole_after_cosmetic"), note="Pothole attended.", actor="ward-engineer-jayanagar", ts=ts(days=1, hours=5),
                    result_override=_verdict(Verdict.UNVERIFIED_COSMETIC, "Same street: the red-brick wall and tree line match. However, the hole is only covered with loose brown gravel and soil, not compacted asphalt; this will wash out with the next rain and does not count as a repair.", same=True, fixed=False, quality="cosmetic", matched=["red-brick wall", "tree line"], mismatch=["loose gravel instead of asphalt"]))

    # ------------------------------------------------- 7. Malleshwaram leak: AI check passed, awaiting citizen
    r = report(13.00310, 77.56430, _ex(
        transcript="8th cross alli road madhya inda neeru chimmuttide, BWSSB pipe odedide anisutte.", transcript_english="On 8th Cross water is gushing from the middle of the road; it looks like a BWSSB pipe has burst.",
        language="kn-en", category=C.WATER_LEAK, severity=4, title="Water pipeline burst on 8th Cross, Malleshwaram",
        description="Treated water gushing through a crack in the road and flowing along the kerb; significant wastage.", landmark="8th Cross, Malleshwaram",
        hazards=[H.TWO_WHEELER_SKID_RISK, H.WATERLOGGING], evidence=EvidenceFlags(recent_digging=False, utility_work_type="water_pipeline", photo_provided=True, photo_usable=True),
        suggested_agency=A.BWSSB, agency_reasoning="Potable water line burst: BWSSB maintenance sub-division.", confidence=0.93,
    ), ts(days=4, hours=2), "mal_leak_before", "citizen-prakash")
    mal = r.cluster["id"]
    created.append(mal)
    closure.resolve(store, ai, store.get_cluster(mal), uploads_dir=uploads_dir, after_photo=photo("mal_leak_after"), note="Pipe clamped and road patched.", actor="bwssb-aee-malleshwaram", ts=ts(days=3, hours=1),
                    result_override=_verdict(Verdict.VERIFIED, "Same stretch: the old houses and kerb match. The road is dry and a fresh rectangular asphalt patch covers the repair spot. Awaiting a citizen photo to confirm it has stayed dry.", same=True, fixed=True, quality="proper", matched=["house facades", "kerb line"]))

    # ------------------------------------------------- 8. Silk Board waterlogging
    r = report(12.91720, 77.62290, _ex(
        transcript="Silk board underpass full water, bikes stuck, knee deep.", language="en", category=C.WATERLOGGING, severity=4,
        title="Severe waterlogging at Silk Board junction underpass", description="Knee-deep water under the flyover; two-wheelers stalled.", landmark="Silk Board junction",
        hazards=[H.WATERLOGGING, H.BLOCKING_TRAFFIC, H.JUNCTION, H.ARTERIAL_ROAD, H.TWO_WHEELER_SKID_RISK], confidence=0.92,
    ), ts(days=1, hours=20), "silkboard_flood_1", "citizen-vignesh")
    silk = r.cluster["id"]
    created.append(silk)
    for i, (txt, lang, when, ph) in enumerate([
        ("ಸಿಲ್ಕ್ ಬೋರ್ಡ್ ಕೆಳಗೆ ನೀರು ನಿಂತಿದೆ, ಗಾಡಿಗಳು ಹೋಗಲು ಆಗುತ್ತಿಲ್ಲ.", "kn", ts(days=1, hours=18), "silkboard_flood_2"),
        ("Silk board flooded again, third time this monsoon.", "en", ts(days=1, hours=15), None),
        ("Silk board junction mein paani bhar gaya hai, ambulance bhi phansi hai.", "hi-en", ts(days=1, hours=12), None),
        ("Water still standing at silk board, drains choked.", "en", ts(days=0, hours=22), None),
    ]):
        report(12.91720 + (i + 1) * 0.00004, 77.62290 - (i + 1) * 0.00003, _ex(
            transcript=txt, transcript_english=txt if lang == "en" else "Silk Board junction is flooded; vehicles cannot pass." if lang == "kn" else "Silk Board junction is flooded; even an ambulance is stuck.",
            language=lang, category=C.WATERLOGGING, severity=4, title="Severe waterlogging at Silk Board junction underpass", description="Waterlogging at Silk Board underpass.",
            landmark="Silk Board junction", hazards=[H.WATERLOGGING, H.BLOCKING_TRAFFIC, H.JUNCTION, H.RECURRING] if "third" in txt else [H.WATERLOGGING, H.BLOCKING_TRAFFIC, H.JUNCTION], confidence=0.9,
        ), when, ph, f"citizen-{i + 20}")

    # ------------------------------------------------- 9. Kadubeesanahalli metro-zone road damage
    created.append(report(12.93920, 77.69620, _ex(
        transcript="Road caved in next to the metro barricade at Kadubeesanahalli, lorry axle got stuck.", language="en", category=C.ROAD_DAMAGE, severity=4,
        title="Road cave-in beside metro barricades at Kadubeesanahalli", description="Carriageway sunk and broken next to Namma Metro Blue Line barricades and a pillar under construction.",
        landmark="Kadubeesanahalli junction", hazards=[H.ARTERIAL_ROAD, H.JUNCTION, H.BLOCKING_TRAFFIC],
        evidence=EvidenceFlags(recent_digging=True, utility_work_type="metro", photo_provided=True, photo_usable=True),
        suggested_agency=A.BMRCL, agency_reasoning="Damage is inside the metro construction zone (barricades and pier visible).", confidence=0.9,
    ), ts(days=3, hours=4), "kad_roaddamage", "citizen-tarun").cluster["id"])

    # ------------------------------------------------- 10. Hebbal dangling wire
    created.append(report(13.03580, 77.59750, _ex(
        transcript="Hebbal flyover ramp hatra wire kelage neethaadtide, spark aagtide!", transcript_english="Near the Hebbal flyover ramp a wire is hanging low and sparking!",
        language="kn-en", category=C.POWER_HAZARD, severity=5, title="Sparking low-hanging wire near Hebbal flyover ramp",
        description="A live wire is hanging at head height from a pole near the flyover ramp and sparking intermittently.", landmark="Hebbal flyover ramp",
        hazards=[H.LIVE_WIRE, H.PEDESTRIAN_RISK, H.ARTERIAL_ROAD], suggested_agency=A.BESCOM, agency_reasoning="Live LT line fault.", confidence=0.95,
    ), ts(hours=4), "heb_wire", "citizen-asha").cluster["id"])

    # ------------------------------------------------- 11. Jayanagar sewage, in progress
    r = report(12.92900, 77.58600, _ex(
        transcript="Sewage overflowing from the manhole near 11th main park entrance since yesterday.", language="en", category=C.SEWAGE_OVERFLOW, severity=3,
        title="Sewage overflow near 11th Main park entrance, Jayanagar", description="Manhole overflowing onto the road near the park entrance.", landmark="11th Main park, Jayanagar",
        hazards=[H.HEALTH_HAZARD, H.PEDESTRIAN_RISK], confidence=0.9,
    ), ts(days=2, hours=1), "jay_sewage", "citizen-mohan")
    created.append(r.cluster["id"])
    closure.set_status(store, store.get_cluster(r.cluster["id"]), ClusterStatus.IN_PROGRESS, "Jetting vehicle scheduled.", "bwssb-aee-jayanagar", ts(days=1, hours=3))

    # ------------------------------------------------- 12. Yelahanka tree, closed without proof
    r = report(13.10070, 77.59630, _ex(
        transcript="Big tree fell across the road near Mother Dairy circle after last night's storm, road fully blocked.", language="en", category=C.FALLEN_TREE, severity=4,
        title="Fallen tree blocking road near Mother Dairy circle, Yelahanka", description="Large tree across the carriageway after a storm.", landmark="Mother Dairy circle, Yelahanka",
        hazards=[H.BLOCKING_TRAFFIC], confidence=0.93,
    ), ts(days=1, hours=14), "yel_tree", "citizen-gowda")
    created.append(r.cluster["id"])
    closure.resolve(store, ai, store.get_cluster(r.cluster["id"]), uploads_dir=uploads_dir, after_photo=None, note="Tree cleared by forest cell.", actor="forest-cell-yelahanka", ts=ts(days=1, hours=2))

    # ------------------------------------------------- 13. Electronic City footpath
    created.append(report(12.84520, 77.66020, _ex(
        transcript="Footpath slabs broken outside the IT park gate, open drain visible, people walk on the road instead.", language="en", category=C.FOOTPATH_DAMAGE, severity=2,
        title="Broken footpath slabs outside IT park gate, Electronic City", description="Several slabs missing exposing the drain; pedestrians forced onto the road.", landmark="IT park gate, Electronic City Phase 1",
        hazards=[H.PEDESTRIAN_RISK, H.OPEN_DRAIN], confidence=0.88,
    ), ts(days=10, hours=3), "ecity_footpath", "citizen-leela").cluster["id"])

    # ------------------------------------------------- 14. Shivajinagar garbage verified
    r = report(12.98570, 77.60570, _ex(
        transcript="Garbage piling up near the market wall on Broadway road, not collected for 3 days.", language="en", category=C.GARBAGE, severity=3,
        title="Uncollected garbage near market wall, Broadway Road", description="Garbage pile at the base of the market wall; collection missed for days.", landmark="Broadway Road market, Shivajinagar",
        hazards=[H.HEALTH_HAZARD], confidence=0.9,
    ), ts(days=12, hours=5), "shiv_garbage_before", "citizen-irfan")
    shiv = r.cluster["id"]
    created.append(shiv)
    report(12.98576, 77.60564, _ex(transcript="Market wall garbage still there, smell unbearable.", language="en", category=C.GARBAGE, severity=3, title="Uncollected garbage near market wall, Broadway Road",
                                      description="Still uncollected.", landmark="Broadway Road", hazards=[H.HEALTH_HAZARD], confidence=0.85), ts(days=11, hours=4), None, "citizen-joseph")
    closure.resolve(store, ai, store.get_cluster(shiv), uploads_dir=uploads_dir, after_photo=photo("shiv_garbage_after"), note="Cleared; auto-tipper route corrected.", actor="swm-jhi-shivajinagar", ts=ts(days=10, hours=2),
                    result_override=_verdict(Verdict.VERIFIED, "Same wall and street; the garbage pile has been removed and the base of the wall is clean.", same=True, fixed=True, quality="proper", matched=["market wall", "street layout"]))
    closure.citizen_verify(store, ai, store.get_cluster(shiv), uploads_dir=uploads_dir, photo=photo("shiv_garbage_after"), reporter_id="citizen-irfan", note="Clean for a week now.", ts=ts(days=9, hours=1),
                           result_override=_verdict(Verdict.VERIFIED, "Citizen photo confirms the spot has stayed clean.", same=True, fixed=True, quality="proper", matched=["market wall"]))

    # ------------------------------------------------- 15. Mahadevapura streetlight verified
    r = report(12.99000, 77.69700, _ex(
        transcript="Street light near the park in Mahadevapura layout 2nd cross not working for a week.", language="en", category=C.STREETLIGHT, severity=2,
        title="Streetlight out on 2nd Cross near park, Mahadevapura", description="Residential lane dark at night for a week.", landmark="2nd Cross park, Mahadevapura",
        hazards=[H.NIGHT_VISIBILITY], confidence=0.88,
    ), ts(days=6, hours=8), "mhd_light_before", "citizen-bhavana")
    mhd = r.cluster["id"]
    created.append(mhd)
    closure.resolve(store, ai, store.get_cluster(mhd), uploads_dir=uploads_dir, after_photo=photo("mhd_light_after"), note="Lamp replaced.", actor="electrical-aee-mahadevapura", ts=ts(days=5, hours=6),
                    result_override=_verdict(Verdict.VERIFIED, "Same lane (parked auto-rickshaw and pole position match); the lamp is now on and the lane is lit.", same=True, fixed=True, quality="proper", matched=["pole", "lane layout"]))
    closure.citizen_verify(store, ai, store.get_cluster(mhd), uploads_dir=uploads_dir, photo=photo("mhd_light_after"), reporter_id="citizen-bhavana", note="Working now, thanks.", ts=ts(days=5, hours=1),
                           result_override=_verdict(Verdict.VERIFIED, "Citizen night photo shows the light working.", same=True, fixed=True, quality="proper", matched=["pole"]))

    # ------------------------------------------------- 16-18. a few more open issues for the map
    created.append(report(12.92400, 77.67300, _ex(
        transcript="Bellandur lake road alli construction debris dump madidare, half road block.", transcript_english="On Bellandur lake road someone has dumped construction debris, half the road is blocked.",
        language="kn-en", category=C.GARBAGE, severity=3, title="Construction debris dumped on Bellandur lake road", description="Debris blocking half the road near the lake bund.", landmark="Bellandur lake road",
        hazards=[H.BLOCKING_TRAFFIC], confidence=0.86,
    ), ts(days=3, hours=2), None, "citizen-sunil").cluster["id"])
    created.append(report(12.96980, 77.75000, _ex(
        transcript="ITPL main road near the bus stop has a long stretch of broken road, very bumpy.", language="en", category=C.ROAD_DAMAGE, severity=3,
        title="Broken stretch on ITPL Main Road near bus stop", description="Long uneven broken stretch of road surface.", landmark="ITPL Main Road, Whitefield",
        hazards=[H.ARTERIAL_ROAD, H.BUS_STOP], confidence=0.85,
    ), ts(days=5, hours=5), None, "citizen-anita").cluster["id"])
    created.append(report(12.91660, 77.61010, _ex(
        transcript="BTM 2nd stage 16th main alli manhole cover illa, raatri yaaradru bilbahudu!", transcript_english="On 16th Main, BTM 2nd Stage, a manhole has no cover; someone could fall in at night!",
        language="kn-en", category=C.OPEN_DRAIN_MANHOLE, severity=5, title="Open manhole on 16th Main, BTM 2nd Stage", description="Uncovered manhole in the middle of a residential road.", landmark="16th Main, BTM 2nd Stage",
        hazards=[H.OPEN_DRAIN, H.PEDESTRIAN_RISK, H.NIGHT_VISIBILITY, H.TWO_WHEELER_SKID_RISK], confidence=0.94,
    ), ts(hours=20), None, "citizen-rekha").cluster["id"])

    refresh_scores(store)
    return {
        "status": "seeded",
        "clusters": len(created),
        "counts": store.counts(),
        "real_photos": have_real_photos(),
        "highlights": {"orr_pothole": orr, "koramangala_fake_closure": kor, "jayanagar_cosmetic": jay, "agara_repeat_failure": agara_new, "silk_board": silk},
    }
