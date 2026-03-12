from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KGSettings:
    data_dir: Path
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60 * 24 * 365
    google_client_id: str = ""
    apple_bundle_id: str = "com.Max0228.BooksBrowser"
    app_store_allow_unsigned_sync: bool = False
    app_store_allow_unsigned_notifications: bool = False
    admin_token: str = ""

    @property
    def users_file(self) -> Path:
        return self.data_dir / "users.json"

    @property
    def users_lock_file(self) -> Path:
        return self.data_dir / "users.json.lock"

    @property
    def app_store_notifications_file(self) -> Path:
        return self.data_dir / "app_store_notifications.ndjson"


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


def load_settings() -> KGSettings:
    default_data_dir = Path(__file__).resolve().parent.parent.parent / "data"

    jwt_secret = os.getenv("JWT_SECRET")
    if not jwt_secret or len(jwt_secret) < 16:
        raise RuntimeError(
            "JWT_SECRET env var is required and must be at least 16 characters. "
            "Set it in your .env file."
        )

    app_store_allow_unsigned_notifications = _env_truthy("APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS")
    if app_store_allow_unsigned_notifications:
        _logger.warning(
            "APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS is ON — "
            "signature verification disabled. DO NOT use in production."
        )

    return KGSettings(
        data_dir=Path(os.getenv("KG_DATA_DIR", str(default_data_dir))),
        jwt_secret=jwt_secret,
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
        apple_bundle_id=os.getenv("APPLE_BUNDLE_ID", "com.Max0228.BooksBrowser"),
        app_store_allow_unsigned_sync=_env_truthy("APP_STORE_ALLOW_UNSIGNED_SYNC"),
        app_store_allow_unsigned_notifications=app_store_allow_unsigned_notifications,
        admin_token=os.getenv("ADMIN_TOKEN", ""),
    )
