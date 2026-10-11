"""Settings, read from environment variables.

SMARTNAV_DATA_DIR   Folder for the database, uploaded runs and map images (default ./data)
SMARTNAV_BASE_URL   Public HTTPS address of this server, e.g. https://nav.myclub.org.au
SMARTNAV_SECRET_KEY Secret for login cookies; generated and saved in the data folder if unset
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path
    base_url: str
    secret_key: str
    max_body_bytes: int = 10 * 1024 * 1024

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'smartnav.db'}"

    @property
    def submissions_dir(self) -> Path:
        return self.data_dir / "submissions"

    @property
    def maps_dir(self) -> Path:
        return self.data_dir / "maps"


def _secret(data_dir: Path) -> str:
    env = os.environ.get("SMARTNAV_SECRET_KEY")
    if env:
        return env
    f = data_dir / "secret_key"
    if f.exists():
        return f.read_text().strip()
    key = secrets.token_urlsafe(48)
    f.write_text(key)
    try:
        f.chmod(0o600)
    except OSError:
        pass
    return key


@lru_cache
def get_settings() -> Settings:
    data_dir = Path(os.environ.get("SMARTNAV_DATA_DIR", "data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "submissions").mkdir(exist_ok=True)
    (data_dir / "maps").mkdir(exist_ok=True)
    base_url = os.environ.get("SMARTNAV_BASE_URL", "http://localhost:8000").rstrip("/")
    return Settings(data_dir=data_dir, base_url=base_url, secret_key=_secret(data_dir))
