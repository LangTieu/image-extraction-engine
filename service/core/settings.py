"""Runtime settings for the API/worker service (P7).

Loaded from environment variables (or a ``.env`` file) with pydantic-settings.
Every value has a working default so the stack runs out of the box with a
SQLite database in ``./data`` and no Redis: the brief's fallback worker is
in-process.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_prefix="SERVICE_"
    )

    app_name: str = "Image Extraction Engine API"
    api_prefix: str = "/v1"

    # Storage
    data_dir: Path = Path("service/data")
    db_url: str = "sqlite:///./service/data/service.db"
    artifacts_dir: Path = Path("service/data/artifacts")
    uploads_dir: Path = Path("service/data/uploads")

    # CORS: comma-separated origins, "*" allows all (dev default).
    cors_origins: str = "*"

    # Extraction
    max_upload_mb: int = 20
    profile: str = "industrial"  # engine profile passed to the worker
    allowed_upload_types: str = (
        "image/png,image/jpeg,image/tiff,image/bmp,image/webp,application/pdf"
    )

    # Security / limits. Empty api_key disables authentication (dev default).
    api_key_env: str = "IMAGE_ENGINE_API_KEY"
    rate_limit_per_minute: int = 60
    max_files_per_job: int = 50  # reject uploads with more files than this
    retention_days: int = 30  # 0 keeps artifacts forever

    # External vision APIs stay off unless explicitly enabled (brief item 7).
    external_vision_apis: bool = False

    # Worker: "inprocess" (default, no Redis needed) or "rq" (Redis queue).
    worker_mode: str = "inprocess"
    redis_url: str = "redis://localhost:6379/0"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.artifacts_dir, self.uploads_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
