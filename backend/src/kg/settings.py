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
    jwt_expiry_minutes: int = 60 * 24 * 7
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "https://wordnexus.lol/auth/web/google/callback"
    chrome_extension_id: str = ""
    apple_bundle_id: str = "com.Max0228.BooksBrowser"
    app_store_allow_unsigned_sync: bool = False
    app_store_allow_unsigned_notifications: bool = False
    admin_token: str = ""
    admin_password: str = ""

    # Quota (USD)
    pro_daily_limit_usd: float = 0.30
    free_daily_limit_usd: float = 0.03

    # LLM
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_temperature: float = 0.3
    judge_temperature: float = 0.1

    # Graph
    similarity_threshold: float = 0.70
    candidate_k: int = 20

    # Vocab
    max_batch_size: int = 500
    max_word_length: int = 200

    # CORS
    cors_origins: tuple[str, ...] = (
        "https://wordnexus.lol",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    )

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
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
        google_redirect_uri=os.getenv("GOOGLE_REDIRECT_URI", "https://wordnexus.lol/auth/web/google/callback"),
        chrome_extension_id=os.getenv("CHROME_EXTENSION_ID", ""),
        apple_bundle_id=os.getenv("APPLE_BUNDLE_ID", "com.Max0228.BooksBrowser"),
        app_store_allow_unsigned_sync=_env_truthy("APP_STORE_ALLOW_UNSIGNED_SYNC"),
        app_store_allow_unsigned_notifications=app_store_allow_unsigned_notifications,
        admin_token=os.getenv("ADMIN_TOKEN", ""),
        admin_password=os.getenv("ADMIN_PASSWORD", ""),
        pro_daily_limit_usd=float(os.getenv("PRO_DAILY_LIMIT_USD", "0.30")),
        free_daily_limit_usd=float(os.getenv("FREE_DAILY_LIMIT_USD", "0.03")),
        cors_origins=tuple(
            os.getenv("CORS_ORIGINS", "https://wordnexus.lol,http://localhost:8000,http://127.0.0.1:8000").split(",")
        ),
    )
