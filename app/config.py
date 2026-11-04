import os
from dataclasses import dataclass
from pathlib import Path

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://bidtrace:bidtrace-local-demo@127.0.0.1:55439/bidtrace",
    )
    upload_dir: Path = Path(os.environ.get("UPLOAD_DIR", "data/uploads"))
    max_upload_bytes: int = MAX_UPLOAD_BYTES
