from __future__ import annotations

from app.ai.heuristic import classify, detect_language, hazards_for, landmark_for, severity_for, utility_type_for
from app.domain import Category, Hazard
from app.geo import haversine_m, location_context, nearest_ward


def test_haversine_known_distance():
    # Silk Board -> Marathahalli bridge is roughly 9.5 km
    d = haversine_m(12.9172, 77.6229, 12.9569, 77.7011)
    assert 9_000 < d < 10_500


def test_nearest_ward():
    assert nearest_ward(12.9262, 77.6816).name == "Bellandur"
    assert nearest_ward(12.9345, 77.6231).name == "Koramangala"
    assert nearest_ward(13.1007, 77.5963).name == "Yelahanka"


def test_location_context_silk_board_has_junction_and_arterial():
    hits = location_context(12.9172, 77.6229)
    types = {h.type for h in hits}
    assert "junction" in types
    assert "arterial_road" in types


def test_location_context_quiet_spot_is_empty():
    assert location_context(12.80, 77.40) == []


def test_classify_code_mixed_kannada():
    cat, conf = classify("ORR service lane alli dodda gundi ide")
    assert cat == Category.POTHOLE
    assert conf > 0.5


def test_classify_kannada_script_and_english():
    assert classify("ರಸ್ತೆಯಲ್ಲಿ ದೊಡ್ಡ ಗುಂಡಿ ಇದೆ")[0] == Category.POTHOLE
    assert classify("street light not working near the park")[0] == Category.STREETLIGHT
    assert classify("garbage dumped at the corner, stinks")[0] == Category.GARBAGE
    assert classify("sewage overflowing from manhole")[0] in (Category.SEWAGE_OVERFLOW, Category.OPEN_DRAIN_MANHOLE)
    assert classify("hello how are you")[0] == Category.OTHER


def test_language_detection():
    assert detect_language("ORR alli dodda gundi ide") == "kn-en"
    assert detect_language("ರಸ್ತೆಯಲ್ಲಿ ಗುಂಡಿ") == "kn"
    assert detect_language("Pothole on the main road") == "en"
    assert detect_language("सड़क पर गड्ढा है") == "hi"


def test_severity_and_hazards():
    text = "Huge pothole near the school, a scooter fell at night and it fills with rain water"
    assert severity_for(text, Category.POTHOLE) >= 4
    hz = hazards_for(text, Category.POTHOLE)
    assert Hazard.NEAR_SCHOOL in hz
    assert Hazard.TWO_WHEELER_SKID_RISK in hz
    assert Hazard.NIGHT_VISIBILITY in hz
    assert Hazard.WATERLOGGING in hz


def test_landmark_and_utility():
    assert landmark_for("Big pothole near Ecospace gate, very deep") == "Ecospace gate"
    assert utility_type_for("they dug for the BWSSB pipeline and left it") == "water_pipeline"
    assert utility_type_for("BESCOM cable trench not closed") == "power_cable"
