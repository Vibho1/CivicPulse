"""Demo photo provider.

Prefers real images in ``data/demo_photos/<name>.jpg``; otherwise synthesises
a simple labelled placeholder with Pillow so the seeder works anywhere.
"""

from __future__ import annotations

import io
import random
from functools import lru_cache
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent / "data" / "demo_photos"

PALETTES = {
    "pothole": ((96, 96, 96), (28, 24, 20)),
    "flood": ((110, 110, 110), (118, 96, 60)),
    "garbage": ((120, 120, 120), (90, 70, 40)),
    "light": ((18, 22, 40), (40, 44, 70)),
    "leak": ((100, 100, 100), (70, 110, 160)),
    "wire": ((140, 150, 170), (30, 30, 30)),
    "sewage": ((105, 105, 105), (40, 50, 40)),
    "tree": ((110, 110, 110), (60, 90, 40)),
    "footpath": ((150, 140, 125), (60, 60, 60)),
    "roaddamage": ((95, 95, 95), (50, 40, 30)),
    "fixed": ((88, 88, 88), (70, 70, 70)),
    "cosmetic": ((96, 96, 96), (150, 120, 80)),
    "wrong": ((120, 170, 120), (200, 180, 60)),
}


def _kind(name: str) -> str:
    n = name.lower()
    if "wrong" in n:
        return "wrong"
    if "cosmetic" in n:
        return "cosmetic"
    if "after" in n or "citizen" in n:
        return "fixed"
    for k in ("flood", "garbage", "light", "leak", "wire", "sewage", "tree", "footpath", "roaddamage"):
        if k in n:
            return k
    return "pothole"


def synthesize(name: str, size: tuple[int, int] = (960, 720)) -> bytes:
    from PIL import Image, ImageDraw

    kind = _kind(name)
    bg, fg = PALETTES[kind]
    rnd = random.Random(name)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    w, h = size
    # horizon / kerb line to give the image some structure
    d.rectangle([0, 0, w, int(h * 0.35)], fill=tuple(min(255, c + 60) for c in bg))
    d.line([(0, int(h * 0.35)), (w, int(h * 0.35))], fill=(200, 200, 200), width=4)
    for _ in range(40):  # asphalt texture
        x, y = rnd.randint(0, w), rnd.randint(int(h * 0.36), h)
        d.point((x, y), fill=tuple(max(0, c - rnd.randint(0, 30)) for c in bg))
    if kind in ("pothole", "roaddamage", "cosmetic", "leak", "sewage"):
        d.ellipse([w * 0.35, h * 0.55, w * 0.68, h * 0.85], fill=fg)
    elif kind == "flood":
        d.rectangle([0, h * 0.55, w, h], fill=fg)
    elif kind == "garbage":
        for _ in range(12):
            x, y = rnd.randint(int(w * 0.3), int(w * 0.7)), rnd.randint(int(h * 0.5), int(h * 0.8))
            d.ellipse([x, y, x + 90, y + 60], fill=tuple(c + rnd.randint(-30, 30) for c in fg))
    elif kind == "light":
        d.rectangle([w * 0.48, h * 0.1, w * 0.52, h * 0.7], fill=(70, 70, 70))
        d.ellipse([w * 0.44, h * 0.05, w * 0.56, h * 0.13], fill=fg)
    elif kind == "wire":
        d.line([(w * 0.1, h * 0.1), (w * 0.5, h * 0.6), (w * 0.9, h * 0.15)], fill=fg, width=5)
    elif kind == "tree":
        d.rectangle([0, h * 0.45, w, h * 0.6], fill=(80, 50, 30))
        d.ellipse([w * 0.2, h * 0.2, w * 0.8, h * 0.7], fill=fg)
    elif kind == "footpath":
        for i in range(6):
            d.rectangle([i * w / 6, h * 0.5, (i + 1) * w / 6 - 8, h], outline=fg, width=3)
        d.rectangle([w * 0.5, h * 0.5, w * 0.66, h], fill=(30, 30, 30))
    elif kind == "wrong":
        d.rectangle([0, 0, w, h * 0.5], fill=fg)
        d.rectangle([w * 0.3, h * 0.2, w * 0.45, h * 0.5], fill=(60, 90, 200))
    d.text((16, 16), f"CivicPulse demo placeholder: {name}", fill=(255, 255, 255))
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=85)
    return out.getvalue()


@lru_cache(maxsize=64)
def photo_bytes(name: str) -> bytes:
    f = DEMO_DIR / f"{name}.jpg"
    if f.exists():
        return f.read_bytes()
    return synthesize(name)


def have_real_photos() -> bool:
    return DEMO_DIR.exists() and any(DEMO_DIR.glob("*.jpg"))
