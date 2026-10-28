"""Geo helpers: distances, ward lookup, sensitive-zone context, EXIF GPS."""

from __future__ import annotations

import io
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bbox_for_radius(lat: float, lng: float, radius_m: float) -> tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lng, max_lng) bounding box around a point."""
    dlat = radius_m / 111_320.0
    dlng = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 0.01))
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng


def _to_local_xy(lat: float, lng: float, ref_lat: float) -> tuple[float, float]:
    """Equirectangular projection to metres around ref_lat (fine at city scale)."""
    x = math.radians(lng) * EARTH_RADIUS_M * math.cos(math.radians(ref_lat))
    y = math.radians(lat) * EARTH_RADIUS_M
    return x, y


def distance_to_segment_m(
    lat: float, lng: float, a: tuple[float, float], b: tuple[float, float]
) -> float:
    """Distance from a point to the segment a-b (both (lat, lng))."""
    px, py = _to_local_xy(lat, lng, lat)
    ax, ay = _to_local_xy(a[0], a[1], lat)
    bx, by = _to_local_xy(b[0], b[1], lat)
    abx, aby = bx - ax, by - ay
    denom = abx * abx + aby * aby
    if denom == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / denom))
    cx, cy = ax + t * abx, ay + t * aby
    return math.hypot(px - cx, py - cy)


# --------------------------------------------------------------------------- #
# Wards
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Ward:
    name: str
    zone: str
    lat: float
    lng: float
    number: int | None = None  # official ward number where known (e.g. 150 Bellandur)


@lru_cache(maxsize=1)
def load_wards() -> tuple[Ward, ...]:
    raw = json.loads((DATA_DIR / "wards.json").read_text(encoding="utf-8"))
    return tuple(Ward(**w) for w in raw["wards"])


def nearest_ward(lat: float, lng: float) -> Ward:
    wards = load_wards()
    return min(wards, key=lambda w: haversine_m(lat, lng, w.lat, w.lng))


# --------------------------------------------------------------------------- #
# Sensitive zones / context for the impact score
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ContextHit:
    name: str
    type: str
    distance_m: float


@lru_cache(maxsize=1)
def _load_hotspots() -> dict:
    return json.loads((DATA_DIR / "hotspots.json").read_text(encoding="utf-8"))


def location_context(lat: float, lng: float, point_radius_m: float = 300.0, road_radius_m: float = 120.0) -> list[ContextHit]:
    """Sensitive places and arterial roads close to a point, nearest first."""
    data = _load_hotspots()
    hits: list[ContextHit] = []
    for p in data["points"]:
        d = haversine_m(lat, lng, p["lat"], p["lng"])
        if d <= point_radius_m:
            hits.append(ContextHit(p["name"], p["type"], round(d)))
    for road in data["arterial_roads"]:
        pts = [tuple(x) for x in road["points"]]
        d = min(distance_to_segment_m(lat, lng, pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        if d <= road_radius_m:
            hits.append(ContextHit(road["name"], "arterial_road", round(d)))
    hits.sort(key=lambda h: h.distance_m)
    return hits


# --------------------------------------------------------------------------- #
# Photos: EXIF GPS + normalisation
# --------------------------------------------------------------------------- #


def _dms_to_deg(dms, ref) -> float | None:
    try:
        deg = float(dms[0]) + float(dms[1]) / 60.0 + float(dms[2]) / 3600.0
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        return None
    if ref in ("S", "W"):
        deg = -deg
    return deg


def extract_exif_gps(image_bytes: bytes) -> tuple[float, float] | None:
    """Return (lat, lng) from EXIF if present. Never raises."""
    try:
        from PIL import Image  # local import keeps Pillow optional at import time

        with Image.open(io.BytesIO(image_bytes)) as im:
            exif = im.getexif()
            gps = exif.get_ifd(0x8825) if exif else None
            if not gps:
                return None
            lat = _dms_to_deg(gps.get(2), gps.get(1))
            lng = _dms_to_deg(gps.get(4), gps.get(3))
            if lat is None or lng is None:
                return None
            return lat, lng
    except Exception:  # noqa: BLE001 - EXIF parsing is best-effort
        return None


def normalise_photo(image_bytes: bytes, max_side: int = 1280, quality: int = 85) -> tuple[bytes, str]:
    """Apply EXIF orientation, downscale, strip metadata, re-encode as JPEG.

    Returns (bytes, mime). Falls back to the original bytes if Pillow cannot
    decode the image.
    """
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(image_bytes)) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.thumbnail((max_side, max_side))
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=quality, optimize=True)
            return out.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001
        return image_bytes, "image/jpeg"


def centroid(points: Iterable[tuple[float, float]]) -> tuple[float, float]:
    pts = list(points)
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def has_exif(image_bytes: bytes) -> bool:
    """True if the image carries any EXIF metadata. Camera photos do; screenshots,
    forwarded (e.g. WhatsApp) and downloaded/stock images usually do not."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as im:
            return len(im.getexif()) > 0
    except Exception:  # noqa: BLE001
        return False


def blur_regions(image_bytes: bytes, regions: Iterable, pad: float = 0.15, quality: int = 85) -> tuple[bytes, int]:
    """Pixelate and blur faces / number plates before a photo is stored publicly.

    ``regions`` are objects or dicts with ``box_2d`` = [ymin, xmin, ymax, xmax] on
    a 0-1000 grid (Gemini's detection format). Returns (jpeg_bytes, regions_blurred);
    the input is returned unchanged if there is nothing to blur or it cannot be decoded.
    """
    boxes = []
    for r in regions or []:
        box = r.get("box_2d") if isinstance(r, dict) else getattr(r, "box_2d", None)
        if not box or len(box) != 4:
            continue
        try:
            ymin, xmin, ymax, xmax = (max(0, min(1000, int(v))) for v in box)
        except (TypeError, ValueError):
            continue
        if ymax > ymin and xmax > xmin:
            boxes.append((ymin, xmin, ymax, xmax))
    if not boxes:
        return image_bytes, 0
    try:
        from PIL import Image, ImageFilter

        with Image.open(io.BytesIO(image_bytes)) as src:
            im = src.convert("RGB")
        w, h = im.size
        done = 0
        for ymin, xmin, ymax, xmax in boxes:
            bw, bh = (xmax - xmin) * w / 1000, (ymax - ymin) * h / 1000
            x0, y0 = max(0, int(xmin * w / 1000 - bw * pad)), max(0, int(ymin * h / 1000 - bh * pad))
            x1, y1 = min(w, int(xmax * w / 1000 + bw * pad)), min(h, int(ymax * h / 1000 + bh * pad))
            if x1 - x0 < 2 or y1 - y0 < 2:
                continue
            region = im.crop((x0, y0, x1, y1))
            tiny = region.resize((max(1, (x1 - x0) // 12), max(1, (y1 - y0) // 12)), Image.Resampling.BILINEAR)
            region = tiny.resize(region.size, Image.Resampling.NEAREST).filter(ImageFilter.GaussianBlur(radius=max(2, (x1 - x0) // 24)))
            im.paste(region, (x0, y0))
            done += 1
        if not done:
            return image_bytes, 0
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue(), done
    except Exception:  # noqa: BLE001
        return image_bytes, 0
