from __future__ import annotations

from kg import deps as deps_mod


def test_default_subscription_payload_wrapper_exposes_named_contract():
    payload = deps_mod._default_subscription_payload()

    assert {
        "is_active",
        "product_id",
        "plan_name",
        "status",
        "is_trial",
        "trial_days",
        "will_renew",
        "expires_at",
        "source",
        "last_synced_at",
    }.issubset(payload.keys())


def test_current_admin_grant_record_wrapper_exposes_named_contract():
    record = deps_mod._current_admin_grant_record({})

    assert {
        "is_active",
        "plan_name",
        "status",
        "source",
        "expires_at",
        "granted_at",
        "granted_by",
        "reason",
        "last_synced_at",
    }.issubset(record.keys())


def test_current_subscription_record_wrapper_exposes_named_contract():
    record = deps_mod._current_subscription_record({})

    assert {
        "is_active",
        "product_id",
        "plan_name",
        "status",
        "is_trial",
        "trial_days",
        "will_renew",
        "expires_at",
        "source",
        "last_synced_at",
    }.issubset(record.keys())


def test_subscription_snapshot_wrappers_preserve_index_resolution_contract():
    users: dict[str, object] = {}

    record = deps_mod._write_subscription_snapshot(
        users,
        "user-1",
        product_id="pro_monthly",
        status="active",
        is_trial=False,
        expires_at=None,
        will_renew=True,
        environment="production",
        transaction_id="txn-1",
        original_transaction_id="orig-1",
        price_display="$4.99",
        source="app_store_sync",
    )

    assert record["subscription"]["product_id"] == "pro_monthly"
    assert record["subscription"]["transaction_id"] == "txn-1"
    assert (
        deps_mod._resolve_user_id_from_subscription_index(users, "orig-1", None)
        == "user-1"
    )
    assert (
        deps_mod._resolve_user_id_from_subscription_index(users, None, "txn-1")
        == "user-1"
    )
