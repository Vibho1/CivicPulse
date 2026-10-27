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

    # Storage
    database_path: str = str(BACKEND_DIR / "data" / "civicpulse.db")
    uploads_dir: str = str(BACKEND_DIR / "data" / "uploads")

    # HTTP
    cors_origins: str = "*"
    public_base_url: str = ""  # e.g. https://civicpulse-xyz.a.run.app (optional)

    # Serve the built PWA from the same process when present.
    frontend_dist: str = str(REPO_DIR / "frontend" / "dist")

    # Demo conveniences
    demo_mode: bool = True

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
