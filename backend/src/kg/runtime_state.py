from __future__ import annotations

from pathlib import Path

from .settings import KGSettings


def runtime_settings(
    *,
    data_dir: Path,
    jwt_secret: str,
    jwt_algorithm: str,
    jwt_expiry_minutes: int,
    google_client_id: str,
    apple_bundle_id: str,
    app_store_allow_unsigned_sync: bool,
    app_store_allow_unsigned_notifications: bool,
    admin_token: str,
) -> KGSettings:
    return KGSettings(
        data_dir=data_dir,
        jwt_secret=jwt_secret,
        jwt_algorithm=jwt_algorithm,
        jwt_expiry_minutes=jwt_expiry_minutes,
        google_client_id=google_client_id,
        apple_bundle_id=apple_bundle_id,
        app_store_allow_unsigned_sync=app_store_allow_unsigned_sync,
        app_store_allow_unsigned_notifications=app_store_allow_unsigned_notifications,
        admin_token=admin_token,
    )


def runtime_users_file(*, explicit_users_file: Path, settings: KGSettings) -> Path:
    return explicit_users_file if str(explicit_users_file) not in {"", "."} else settings.users_file


def runtime_users_lock_file(*, explicit_users_lock_file: Path, settings: KGSettings) -> Path:
    return explicit_users_lock_file if str(explicit_users_lock_file) not in {"", "."} else settings.users_lock_file


def runtime_notifications_file(*, explicit_notifications_file: Path, settings: KGSettings) -> Path:
    return (
        explicit_notifications_file
        if str(explicit_notifications_file) not in {"", "."}
        else settings.app_store_notifications_file
    )
