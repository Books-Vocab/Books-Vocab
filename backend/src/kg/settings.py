from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger(__name__)

DEFAULT_PUBLIC_WEB_BASE_URL = "https://wordnexus.lol"
_GOOGLE_WEB_CALLBACK_PATH = "/auth/web/google/callback"
_APPLE_WEB_CALLBACK_PATH = "/auth/web/apple/callback"

_DEFAULT_CORS: tuple[str, ...] = (
    DEFAULT_PUBLIC_WEB_BASE_URL,
    "http://localhost:8000",
    "http://127.0.0.1:8000",
)


@dataclass(frozen=True)
class KGSettings:
    data_dir: Path
    jwt_secret: str
    public_web_base_url: str = DEFAULT_PUBLIC_WEB_BASE_URL
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60 * 24 * 7
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = DEFAULT_PUBLIC_WEB_BASE_URL + _GOOGLE_WEB_CALLBACK_PATH
    chrome_extension_id: str = ""
    apple_bundle_id: str = "com.Max0228.BooksAndVocab"
    apple_service_id: str = "com.Max0228.BooksAndVocab.web"
    app_store_allow_unsigned_sync: bool = False
    app_store_allow_unsigned_notifications: bool = False
    admin_token: str = ""
    admin_password: str = ""

    # Quota (USD)
    pro_daily_limit_usd: float = 0.30
    free_daily_limit_usd: float = 0.03

    # Rate limiting — anonymous (no-auth) requests are keyed off the client IP
    # extracted from X-Forwarded-For. This is the number of TRUSTED proxy hops
    # in front of the app: the key is taken from the Nth-from-end XFF segment.
    # Default 1 matches the current single-layer bare Caddy deployment, which
    # appends the real client IP to the END of XFF (so [-1] is the real IP).
    # Set to N+1 only if N additional trusted proxies (CDN/ALB) are placed in
    # front of Caddy. See docs/reference/host_topology.md.
    rate_limit_trusted_hops: int = 1

    # LLM
    embedding_model: str = "gemini-embedding-2-preview"
    embedding_dim: int = 3072
    gemini_temperature: float = 0.3
    judge_temperature: float = 0.1
    # Minimum confidence for a judge link to be accepted. Lower this when
    # switching to a lower-calibrated judge model to avoid silently rejecting
    # all links. Default 0.7 preserves prior hardcoded behavior.
    judge_confidence_threshold: float = 0.7

    # Graph
    similarity_threshold: float = 0.70
    candidate_k: int = 20

    # Vocab
    max_batch_size: int = 500
    max_word_length: int = 200

    # CORS
    cors_origins: tuple[str, ...] = _DEFAULT_CORS

    # Podcast storage backend.
    # When `podcast_bucket` is set, audio + subtitle reads go to S3-compatible
    # object storage (Lightsail Object Storage in prod). When unset, the
    # backend falls back to the on-disk layout under `data_dir/podcasts/` —
    # this preserves dev-time iteration and provides a transition window
    # before older series are re-uploaded in m4a form.
    podcast_bucket: str | None = None
    podcast_bucket_region: str = "ap-northeast-1"
    # Optional S3-compatible endpoint URL. Standard AWS S3 leaves this empty;
    # Lightsail Object Storage works with the default region-derived URL too,
    # but the env var is wired through for custom endpoints (e.g. R2 / minio
    # during local testing).
    podcast_bucket_endpoint_url: str | None = None

    @property
    def users_file(self) -> Path:
        return self.data_dir / "users.json"

    @property
    def users_lock_file(self) -> Path:
        return self.data_dir / "users.json.lock"

    @property
    def podcasts_dir(self) -> Path:
        return self.data_dir / "podcasts"

    @property
    def app_store_notifications_file(self) -> Path:
        return self.data_dir / "app_store_notifications.ndjson"

    @property
    def apple_redirect_uri(self) -> str:
        return self.public_web_base_url.rstrip("/") + _APPLE_WEB_CALLBACK_PATH


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        _logger.warning(
            "Env var %s=%r is not a valid float; falling back to default %s.",
            name,
            raw,
            default,
        )
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        _logger.warning(
            "Env var %s=%r is not a valid int; falling back to default %s.",
            name,
            raw,
            default,
        )
        return default


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
        public_web_base_url=os.getenv("PUBLIC_WEB_BASE_URL", DEFAULT_PUBLIC_WEB_BASE_URL).rstrip("/"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "gemini-embedding-2-preview"),
        embedding_dim=_env_int("EMBEDDING_DIM", 3072),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
        google_redirect_uri=os.getenv(
            "GOOGLE_REDIRECT_URI",
            DEFAULT_PUBLIC_WEB_BASE_URL + _GOOGLE_WEB_CALLBACK_PATH,
        ),
        chrome_extension_id=os.getenv("CHROME_EXTENSION_ID", ""),
        apple_bundle_id=os.getenv("APPLE_BUNDLE_ID", "com.Max0228.BooksAndVocab"),
        apple_service_id=os.getenv("APPLE_SERVICE_ID", "com.Max0228.BooksAndVocab.web"),
        app_store_allow_unsigned_sync=_env_truthy("APP_STORE_ALLOW_UNSIGNED_SYNC"),
        app_store_allow_unsigned_notifications=app_store_allow_unsigned_notifications,
        admin_token=os.getenv("ADMIN_TOKEN", ""),
        admin_password=os.getenv("ADMIN_PASSWORD", ""),
        pro_daily_limit_usd=_env_float("PRO_DAILY_LIMIT_USD", 0.30),
        free_daily_limit_usd=_env_float("FREE_DAILY_LIMIT_USD", 0.03),
        rate_limit_trusted_hops=_env_int("RATE_LIMIT_TRUSTED_HOPS", 1),
        judge_confidence_threshold=_env_float("JUDGE_CONFIDENCE_THRESHOLD", 0.7),
        cors_origins=tuple(
            o.strip()
            for o in os.getenv(
                "CORS_ORIGINS",
                ",".join(_DEFAULT_CORS),
            ).split(",")
            if o.strip()
        ),
        podcast_bucket=(os.getenv("PODCAST_BUCKET") or None),
        podcast_bucket_region=os.getenv("PODCAST_BUCKET_REGION", "ap-northeast-1"),
        podcast_bucket_endpoint_url=(os.getenv("PODCAST_BUCKET_ENDPOINT_URL") or None),
    )
