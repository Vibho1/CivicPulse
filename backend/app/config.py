"""Runtime configuration (environment variables / .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Gemini. Leave the key empty to run fully offline with the heuristic parser.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_s: int = 60
    # Report parsing is on the citizen's critical path (PRD: p95 < 5 s), so give up on
    # the model sooner there and fall back to the offline parser.
    gemini_parse_timeout_s: int = 15
    # ...or call Gemini through Vertex AI with Application Default Credentials (e.g. the
    # Cloud Run service account) instead of an API key.
    gemini_use_vertex: bool = False
    google_cloud_project: str = ""  # empty = the ADC project
    google_cloud_location: str = "global"

    # Storage
    database_path: str = str(BACKEND_DIR / "data" / "civicpulse.db")
    uploads_dir: str = str(BACKEND_DIR / "data" / "uploads")

    # HTTP
    cors_origins: str = "*"
    public_base_url: str = ""  # e.g. https://civicpulse-xyz.a.run.app (optional)

    # Serve the built PWA from the same process when present.
    frontend_dist: str = str(REPO_DIR / "frontend" / "dist")

    # Intake limits (PRD: photo up to 10 MB, voice note up to 30 s).
    max_image_mb: int = 10
    max_audio_mb: int = 10
    max_audio_s: int = 30

    # Anti-spam: reject the same reporter filing the same category within this
    # radius and time window (PRD: 1 km / 5 min). Set either to 0 to disable.
    duplicate_window_s: int = 300
    duplicate_radius_m: int = 1000

    # Optional webhook (e.g. a WhatsApp / SMS bridge) that receives "send a proof
    # photo" requests when an official marks an issue resolved. The in-app inbox
    # (GET /api/notifications) works without it.
    notify_webhook_url: str = ""

    # Voice notes can identify a person (PRD privacy NFR). They are only served publicly
    # when this is on; the reporter still gets their own playback link.
    public_audio: bool = False

    # WhatsApp Cloud API intake (PRD OQ-1, optional). Disabled unless the verify token is set.
    whatsapp_verify_token: str = ""
    whatsapp_access_token: str = ""
    whatsapp_app_secret: str = ""  # verifies X-Hub-Signature-256 on webhook calls
    whatsapp_phone_number_id: str = ""
    whatsapp_graph_version: str = "v21.0"

    # Demo conveniences
    demo_mode: bool = True
    # Load the Bengaluru demo story at startup when the database is empty (e.g. a fresh
    # Cloud Run deployment). Never touches a database that already has reports.
    seed_on_startup: bool = False

    @property
    def db_path(self) -> Path:
        return Path(self.database_path)

    @property
    def uploads_path(self) -> Path:
        return Path(self.uploads_dir)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.uploads_path.mkdir(parents=True, exist_ok=True)
    return settings
