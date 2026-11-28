import os
from dataclasses import dataclass, field
from pathlib import Path

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
DEFAULT_REVIEW_ORIGINS = (
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8001",
    "http://127.0.0.1:8001",
)


@dataclass(frozen=True)
class Settings:
    """Runtime settings; environment values are read when a Settings is constructed."""

    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://bidtrace:bidtrace-local-demo@127.0.0.1:55439/bidtrace",
        )
    )
    upload_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("UPLOAD_DIR", "data/uploads"))
    )
    allowed_review_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            origin.strip()
            for origin in os.environ.get("REVIEW_ORIGINS", ", ".join(DEFAULT_REVIEW_ORIGINS)).split(
                ","
            )
            if origin.strip()
        )
    )
    session_secret: str = field(
        default_factory=lambda: os.environ.get("SESSION_SECRET", "bidtrace-local-demo-secret")
    )
    auth_enabled: bool = field(
        default_factory=lambda: os.environ.get("AUTH_ENABLED", "1").lower()
        not in {"0", "false", "no", "off"}
    )
