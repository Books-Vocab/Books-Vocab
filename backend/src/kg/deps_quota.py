"""Quota check helpers extracted from deps.py."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Response

from .exceptions import QuotaExceededError


def _is_pro(user: dict) -> bool:
    from .billing import current_pro_entitlement_record
    return bool(current_pro_entitlement_record(user.get("record")).get("is_active"))


def _with_quota_check[TResult](
    user: dict, call_type: str, response: Response | None, handler: Callable[[], TResult],
) -> TResult:
    quota = _check_quota(user, call_type, response)
    result = handler()
    _apply_quota_headers(response, quota)
    return result


def _check_quota(user: dict, call_type: str, response: Response | None) -> dict:
    from .quota_service import check_and_get_quota
    pro = _is_pro(user)
    quota = check_and_get_quota(user["id"], call_type, is_pro=pro)
    if quota["exceeded"]:
        raise QuotaExceededError(
            quota["reset_seconds"],
            headers={"X-Quota-Fraction": "0.0", "X-Quota-Reset": str(quota["reset_seconds"])},
        )
    return quota


def _apply_quota_headers(response: Response | None, quota: dict) -> None:
    if response is not None:
        response.headers["X-Quota-Fraction"] = str(quota["fraction"])
        response.headers["X-Quota-Reset"] = str(quota["reset_seconds"])
