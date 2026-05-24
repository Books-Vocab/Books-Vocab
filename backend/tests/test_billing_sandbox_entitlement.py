"""Security regression: sandbox transactions must not yield a real Pro entitlement.

App Store sandbox transactions are free and signed by Apple's sandbox CA. The JWS
cert-chain + bundleId verification passes for them, and the *trusted* JWS payload
carries `environment: "Sandbox"`. Without an environment gate at the entitlement
read layer, a client could replay a sandbox transaction to obtain real Pro access.
"""

from __future__ import annotations

from kg.billing import build_entitlements_response, current_pro_entitlement_record


def _user_with_subscription(environment: str, *, status: str = "active") -> dict:
    return {
        "subscription": {
            "is_active": status in {"active", "trial", "grace_period"},
            "status": status,
            "product_id": "pro_monthly",
            "environment": environment,
        }
    }


# ── entitlement gate: non-production environments are not entitled ─────────────

def test_sandbox_subscription_does_not_grant_pro(monkeypatch):
    monkeypatch.delenv("KG_ALLOW_SANDBOX_PURCHASE", raising=False)
    user = _user_with_subscription("Sandbox")
    rec = current_pro_entitlement_record(user)
    assert rec["is_active"] is False, "sandbox subscription must not be entitled in production"
    assert rec["status"] == "inactive"


def test_sandbox_subscription_case_insensitive(monkeypatch):
    monkeypatch.delenv("KG_ALLOW_SANDBOX_PURCHASE", raising=False)
    for env in ("sandbox", "SANDBOX", "Xcode", "xcode"):
        rec = current_pro_entitlement_record(_user_with_subscription(env))
        assert rec["is_active"] is False, f"environment {env!r} must not be entitled"


def test_production_subscription_still_grants_pro(monkeypatch):
    monkeypatch.delenv("KG_ALLOW_SANDBOX_PURCHASE", raising=False)
    rec = current_pro_entitlement_record(_user_with_subscription("Production"))
    assert rec["is_active"] is True
    assert rec["status"] == "active"


def test_missing_environment_defaults_to_production(monkeypatch):
    """Legacy snapshots written before the environment column existed must stay entitled."""
    monkeypatch.delenv("KG_ALLOW_SANDBOX_PURCHASE", raising=False)
    user = {
        "subscription": {
            "is_active": True,
            "status": "active",
            "product_id": "pro_monthly",
        }
    }
    rec = current_pro_entitlement_record(user)
    assert rec["is_active"] is True, "legacy snapshot without environment must remain entitled"


# ── env gate keeps sandbox testing possible ───────────────────────────────────

def test_sandbox_subscription_allowed_when_env_gate_on(monkeypatch):
    monkeypatch.setenv("KG_ALLOW_SANDBOX_PURCHASE", "1")
    rec = current_pro_entitlement_record(_user_with_subscription("Sandbox"))
    assert rec["is_active"] is True, "KG_ALLOW_SANDBOX_PURCHASE=1 must re-enable sandbox entitlement"


# ── full response path also gated ─────────────────────────────────────────────

def test_build_entitlements_response_gates_sandbox(monkeypatch):
    monkeypatch.delenv("KG_ALLOW_SANDBOX_PURCHASE", raising=False)
    resp = build_entitlements_response(_user_with_subscription("Sandbox"))
    assert resp.pro.is_active is False


# ── admin grant must not be affected by the environment gate ──────────────────

def test_admin_grant_unaffected_by_environment_gate(monkeypatch):
    from datetime import UTC, datetime, timedelta

    monkeypatch.delenv("KG_ALLOW_SANDBOX_PURCHASE", raising=False)
    future = (datetime.now(tz=UTC) + timedelta(days=30)).isoformat()
    user = {
        "admin_grant": {"is_active": True, "expires_at": future},
        "subscription": {"is_active": True, "status": "active", "environment": "Sandbox"},
    }
    rec = current_pro_entitlement_record(user)
    assert rec["source"] == "admin"
    assert rec["is_active"] is True
