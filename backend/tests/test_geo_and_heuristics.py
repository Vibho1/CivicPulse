from __future__ import annotations

import io

from app.ai.base import Media, ParseInput
from app.ai.heuristic import (
    HeuristicAI,
    classify,
    detect_language,
    dimensions_for,
    hazards_for,
    is_emergency,
    landmark_for,
    severity_for,
    utility_type_for,
)
from app.domain import Category, Hazard
from app.geo import blur_regions, has_exif, haversine_m, location_context, nearest_ward


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
    assert classify("street light not working near the park")[0] == Category.STREETLIGHT_OUTAGE
    assert classify("garbage dumped at the corner, stinks")[0] == Category.GARBAGE_DUMP
    assert classify("sewage overflowing from manhole")[0] in (Category.SEWAGE_OVERFLOW, Category.OPEN_DRAIN_MANHOLE)
    assert classify("BESCOM cable trench dug up and not restored")[0] == Category.UNRESTORED_UTILITY_TRENCH
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


def test_emergency_detection_uses_whole_words():
    assert is_emergency("Live wire fell on the road, a man got electrocuted, call ambulance")
    assert is_emergency("Transformer on fire near the bus stop")
    assert is_emergency("ರಸ್ತೆಯಲ್ಲಿ ಬೆಂಕಿ")
    assert not is_emergency("Firewood dumped on the footpath")
    assert not is_emergency("Big pothole near Ecospace")


def test_dimensions_from_text():
    d = dimensions_for("pothole about 30 cm deep and 1.2 m wide, 2 feet long")
    assert (d.depth, d.width, d.length) == (30.0, 120.0, 61.0)
    assert dimensions_for("big pothole") is None


def test_photo_only_report_offline_is_low_confidence_not_a_guess():
    ex = HeuristicAI().parse_report(ParseInput(text=None, audio=None, photo=Media(b"x", "image/jpeg"), lat=12.9, lng=77.6, ward="Bellandur"))
    assert ex.category == Category.OTHER and ex.confidence < 0.3


def _jpeg(exif: bool) -> bytes:
    from PIL import Image

    im = Image.new("RGB", (100, 80), (200, 200, 200))
    for x in range(40, 60):
        for y in range(30, 50):
            im.putpixel((x, y), (0, 0, 0) if (x + y) % 2 else (255, 255, 255))
    out = io.BytesIO()
    if exif:
        e = Image.Exif()
        e[0x0110] = "Pixel 9"  # camera model
        im.save(out, format="JPEG", exif=e, quality=95)
    else:
        im.save(out, format="JPEG", quality=95)
    return out.getvalue()


def test_has_exif_tells_camera_photos_from_stripped_ones():
    assert has_exif(_jpeg(exif=True))
    assert not has_exif(_jpeg(exif=False))
    assert not has_exif(b"not an image")


def test_blur_regions_scrubs_only_the_boxes():
    from PIL import Image

    src = _jpeg(exif=False)
    out, n = blur_regions(src, [{"kind": "face", "box_2d": [375, 400, 625, 600]}], pad=0)
    assert n == 1 and out != src
    before, after = Image.open(io.BytesIO(src)), Image.open(io.BytesIO(out))
    # the checkerboard inside the box is smoothed away; a corner outside it is untouched
    inside = [after.getpixel((x, 40))[0] for x in range(42, 58)]
    assert max(inside) - min(inside) < 120
    assert abs(after.getpixel((5, 5))[0] - before.getpixel((5, 5))[0]) < 8
    assert blur_regions(src, []) == (src, 0)
    assert blur_regions(src, [{"kind": "face", "box_2d": [10, 10, 5, 5]}]) == (src, 0)  # degenerate box ignored
