"""Compatibility re-exports for :mod:`kg.api`.

Keep the legacy import surface centralized here so ``kg.api`` can focus on
app bootstrap and route composition while long-lived tests/callers retain the
same symbols.
"""

from __future__ import annotations

from .app_exception_handlers import _redact_validation_body, _redact_validation_payload  # noqa: F401
from .app_middleware import _anon_rate_limit_key  # noqa: F401
from .deps import (  # noqa: F401
    _MAX_USER_LOCKS,
    _USER_LOCKS,
    _USER_LOCKS_MUTEX,
    _apply_quota_headers,
    _build_entitlements_response,
    _card_response,
    _card_store,
    _check_quota,
    _collect_account_ids_for_deletion,
    _create_jwt_token,
    _current_admin_grant_record,
    _current_subscription_record,
    _default_subscription_payload,
    _embedding_store,
    _get_settings,
    _graph_store,
    _is_pro,
    _notification_status,
    _parse_datetime,
    _resolve_and_link_user,
    _resolve_user_id_from_subscription_index,
    _review_event_store,
    _with_quota_check,
    _write_subscription_snapshot,
    get_current_user,
    get_user_lock,
    security,
)
from .routers.auth import auth_verify  # noqa: F401
from .routers.billing import (  # noqa: F401
    app_store_notifications,
    reconcile_app_store_subscription,
    sync_app_store_subscription,
)
from .routers.pipeline import _run_pipeline_background, run_pipeline  # noqa: F401
from .routers.static_pages import get_guide, get_privacy_policy, get_support, get_terms  # noqa: F401
from .routers.translate import translate_explain, translate_phrase, translate_quick  # noqa: F401
from .routers.user import (  # noqa: F401
    delete_user_account,
    get_user_config,
    get_user_entitlements,
    get_user_quota,
    health,
    update_user_config,
)
from .routers.vocab import (  # noqa: F401
    add_vocab,
    archive_word,
    delete_word,
    get_graph_links,
    list_vocab,
    lookup_word,
    pull_review_events,
    push_review,
    push_review_events,
)

__all__ = [
    "_MAX_USER_LOCKS",
    "_USER_LOCKS",
    "_USER_LOCKS_MUTEX",
    "_anon_rate_limit_key",
    "_apply_quota_headers",
    "_build_entitlements_response",
    "_card_response",
    "_card_store",
    "_check_quota",
    "_collect_account_ids_for_deletion",
    "_create_jwt_token",
    "_current_admin_grant_record",
    "_current_subscription_record",
    "_default_subscription_payload",
    "_embedding_store",
    "_get_settings",
    "_graph_store",
    "_is_pro",
    "_notification_status",
    "_parse_datetime",
    "_redact_validation_body",
    "_redact_validation_payload",
    "_resolve_and_link_user",
    "_resolve_user_id_from_subscription_index",
    "_review_event_store",
    "_run_pipeline_background",
    "_with_quota_check",
    "_write_subscription_snapshot",
    "add_vocab",
    "app_store_notifications",
    "archive_word",
    "auth_verify",
    "delete_user_account",
    "delete_word",
    "get_current_user",
    "get_graph_links",
    "get_guide",
    "get_privacy_policy",
    "get_support",
    "get_terms",
    "get_user_config",
    "get_user_entitlements",
    "get_user_lock",
    "get_user_quota",
    "health",
    "list_vocab",
    "lookup_word",
    "pull_review_events",
    "push_review",
    "push_review_events",
    "reconcile_app_store_subscription",
    "run_pipeline",
    "security",
    "sync_app_store_subscription",
    "translate_explain",
    "translate_phrase",
    "translate_quick",
    "update_user_config",
]
