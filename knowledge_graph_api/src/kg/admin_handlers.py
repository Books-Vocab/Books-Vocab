from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from .user_store import resolve_mochi_api_key_from_config


def require_admin(token: str | None, *, admin_token: str) -> None:
    if not admin_token:
        raise HTTPException(403, "ADMIN_TOKEN not configured")
    if token != admin_token:
        raise HTTPException(403, "Forbidden")


def admin_ui_response(token: str | None, *, admin_token: str, admin_html: str) -> HTMLResponse:
    require_admin(token, admin_token=admin_token)
    return HTMLResponse(admin_html)


def admin_stats_response(
    token: str | None,
    *,
    admin_token: str,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    get_all_stats: Callable[[], dict[str, Any]],
    data_dir: Any,
    card_store_factory: Callable[[Any], Any],
) -> dict[str, Any]:
    require_admin(token, admin_token=admin_token)

    users_data = load_users()
    token_stats = get_all_stats()

    in_per_m = 0.10
    out_per_m = 0.40
    emb_per_m = 0.00025

    result = []
    for uid, info in users_data.items():
        if uid.startswith("_"):
            continue

        user_dir = data_dir / "users" / uid
        vocab_count = 0
        try:
            store = card_store_factory(user_dir)
            vocab_count = sum(1 for card in store.all() if not card.is_deleted)
        except Exception:
            pass

        utoken = token_stats.get(uid, {})
        total_input = sum(d["input_tokens"] for d in utoken.values())
        total_output = sum(d["output_tokens"] for d in utoken.values())

        est_cost = 0.0
        for call_type, data in utoken.items():
            if call_type == "embed":
                est_cost += (data["input_tokens"] / 1_000_000) * emb_per_m
            else:
                est_cost += (data["input_tokens"] / 1_000_000) * in_per_m
                est_cost += (data["output_tokens"] / 1_000_000) * out_per_m

        config = info.get("config", {}) if isinstance(info, dict) else {}
        result.append(
            {
                "user_id": uid,
                "email": info.get("email") if isinstance(info, dict) else None,
                "provider": info.get("provider") if isinstance(info, dict) else None,
                "last_login": info.get("last_login") if isinstance(info, dict) else None,
                "vocab_count": vocab_count,
                "has_mochi": bool(resolve_mochi_api_key_from_config(config)),
                "tokens": utoken,
                "total_input": total_input,
                "total_output": total_output,
                "est_cost_usd": round(est_cost, 6),
            }
        )

    result.sort(key=lambda item: item["vocab_count"], reverse=True)
    return {"users": result}


def admin_logs_response(
    token: str | None,
    *,
    admin_token: str,
    log_getter: Callable[..., list[dict[str, Any]]],
    n: int,
    level: str | None,
) -> dict[str, Any]:
    require_admin(token, admin_token=admin_token)
    return {"logs": log_getter(n=n, level=level or None)}


def admin_run_tests_response(
    token: str | None,
    *,
    admin_token: str,
    req: Any,
    run_pytest_matrix: Callable[..., dict[str, Any]],
    store_last_test_run: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    require_admin(token, admin_token=admin_token)
    selected = req.itemIds if req else []
    return store_last_test_run(run_pytest_matrix(selected_items=selected))


def admin_last_test_run_response(
    token: str | None,
    *,
    admin_token: str,
    get_last_test_run: Callable[[], dict[str, Any] | None],
) -> dict[str, Any]:
    require_admin(token, admin_token=admin_token)
    last_run = get_last_test_run()
    if last_run is None:
        return {"status": "idle"}
    return last_run


def admin_test_catalog_response(
    token: str | None,
    *,
    admin_token: str,
    build_test_catalog: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    require_admin(token, admin_token=admin_token)
    return build_test_catalog()


def admin_tests_ui_response(token: str | None, *, admin_token: str, admin_tests_html: str) -> HTMLResponse:
    require_admin(token, admin_token=admin_token)
    return HTMLResponse(admin_tests_html)
