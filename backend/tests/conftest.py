from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai import ResilientAI  # noqa: E402
from app.ai.heuristic import HeuristicAI  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.store import Store  # noqa: E402


@pytest.fixture()
def store() -> Store:
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture()
def uploads(tmp_path: Path) -> Path:
    d = tmp_path / "uploads"
    d.mkdir()
    return d


@pytest.fixture()
def ai() -> ResilientAI:
    return ResilientAI(None, HeuristicAI())


@pytest.fixture()
def jpeg() -> bytes:
    from PIL import Image

    im = Image.new("RGB", (64, 48), (90, 90, 90))
    out = io.BytesIO()
    im.save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture()
def client(tmp_path: Path, store: Store, ai: ResilientAI):
    from fastapi.testclient import TestClient

    settings = Settings(
        gemini_api_key="",
        database_path=str(tmp_path / "test.db"),
        uploads_dir=str(tmp_path / "uploads"),
        frontend_dist=str(tmp_path / "no-dist"),
        demo_mode=True,
    )
    app = create_app(settings=settings, store=store, ai=ai)
    with TestClient(app) as c:
        yield c
