"""AI cost / token summary for a single user (admin observability).

Aggregates ``token_usage.db`` rows into three orthogonal breakdowns —
``by_service`` / ``by_model`` / ``by_call_type`` — plus totals and the
pricing assumptions used to compute USD cost. Time-bounded by ``range``
(default ``month`` = current calendar month, UTC).

Read-only. Never writes.

Assumptions (documented in response under ``pricing_assumptions``):
  * The ``token_usage`` schema does not record model name. Model is
    inferred from ``call_type``:
      - ``embed`` → ``gemini-embedding-2-preview``
      - everything else → ``gemini-2.5-flash-lite``
    Matches the production defaults in ``settings.py`` /
    ``embeddings.py``. Cost-per-token is sourced from
    :mod:`kg.quota_service` (``INPUT_PER_M`` / ``OUTPUT_PER_M`` /
    ``EMBED_PER_M``) so this module stays in lockstep with the live
    quota math.
  * Service grouping (judge / translate / pipeline / other) is by
    ``call_type`` prefix — see ``_SERVICE_MAP``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# call_type → service bucket
_SERVICE_MAP: dict[str, str] = {
    "judge": "judge",
    "manual_link_judge": "judge",
    "translate_quick": "translate",
    "translate_phrase": "translate",
    "translate_explain": "translate",
    "enrich": "pipeline",
    "embed": "pipeline",
}

# call_type → inferred model name
_MODEL_MAP: dict[str, str] = {
    "embed": "gemini-embedding-2-preview",
}
_DEFAULT_MODEL = "gemini-2.5-flash-lite"


_VALID_RANGES = ("24h", "7d", "30d", "month", "all")


def _since_iso(range_: str) -> str | None:
    """Resolve range token → ISO cutoff (UTC) or ``None`` for all-time.

    ``month`` = start of current UTC calendar month at 00:00:00.
    """
    now = datetime.now(UTC)
    if range_ == "24h":
        return datetime.fromtimestamp(now.timestamp() - 86400, tz=UTC).isoformat()
    if range_ == "7d":
        return datetime.fromtimestamp(now.timestamp() - 7 * 86400, tz=UTC).isoformat()
    if range_ == "30d":
        return datetime.fromtimestamp(now.timestamp() - 30 * 86400, tz=UTC).isoformat()
    if range_ == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start.isoformat()
    if range_ == "all":
        return None
    raise ValueError(f"invalid range: {range_}")


def _service_for(call_type: str) -> str:
    return _SERVICE_MAP.get(call_type, "other")


def _model_for(call_type: str) -> str:
    return _MODEL_MAP.get(call_type, _DEFAULT_MODEL)


def get_user_cost_summary(user_id: str, *, range_: str = "month") -> dict[str, Any]:
    """Return per-user token + cost breakdown for the given range.

    Shape:
        ``{user_id, range, since, total_input_tokens, total_output_tokens,
        total_tokens, total_cost_usd, by_service, by_model, by_call_type,
        pricing_assumptions}``

    Empty when no rows match — never raises ``IndexError`` on an empty
    table, never inserts a default user.
    """
    if range_ not in _VALID_RANGES:
        raise ValueError(f"invalid range: {range_}")

    # Import lazily so unit tests can monkeypatch DATA_DIR before module
    # initialises its SQLite connection.
    from .quota_service import EMBED_PER_M, INPUT_PER_M, OUTPUT_PER_M, token_cost_usd
    from .token_tracker import _get_conn, _lock

    since = _since_iso(range_)

    with _lock:
        conn = _get_conn()
        if since is None:
            rows = conn.execute(
                """
                SELECT call_type,
                       COUNT(*)            AS cnt,
                       SUM(input_tokens)   AS total_in,
                       SUM(output_tokens)  AS total_out
                FROM token_usage
                WHERE user_id = ?
                GROUP BY call_type
                """,
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT call_type,
                       COUNT(*)            AS cnt,
                       SUM(input_tokens)   AS total_in,
                       SUM(output_tokens)  AS total_out
                FROM token_usage
                WHERE user_id = ? AND created_at >= ?
                GROUP BY call_type
                """,
                (user_id, since),
            ).fetchall()

    by_call_type: dict[str, dict[str, Any]] = {}
    by_service: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    total_in = 0
    total_out = 0
    total_cost = 0.0
    total_calls = 0

    for call_type, cnt, t_in, t_out in rows:
        ti = int(t_in or 0)
        to = int(t_out or 0)
        c = int(cnt or 0)
        cost = token_cost_usd(call_type, ti, to)

        total_in += ti
        total_out += to
        total_cost += cost
        total_calls += c

        by_call_type[call_type] = {
            "calls": c,
            "input_tokens": ti,
            "output_tokens": to,
            "cost_usd": round(cost, 6),
        }

        svc = _service_for(call_type)
        bucket = by_service.setdefault(svc, {
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
        })
        bucket["calls"] += c
        bucket["input_tokens"] += ti
        bucket["output_tokens"] += to
        bucket["cost_usd"] += cost

        mdl = _model_for(call_type)
        mbucket = by_model.setdefault(mdl, {
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
        })
        mbucket["calls"] += c
        mbucket["input_tokens"] += ti
        mbucket["output_tokens"] += to
        mbucket["cost_usd"] += cost

    # Round cost_usd at the leaves once aggregation is complete.
    for bucket in (*by_service.values(), *by_model.values()):
        bucket["cost_usd"] = round(bucket["cost_usd"], 6)

    return {
        "user_id": user_id,
        "range": range_,
        "since": since,
        "total_calls": total_calls,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_tokens": total_in + total_out,
        "total_cost_usd": round(total_cost, 6),
        "by_service": by_service,
        "by_model": by_model,
        "by_call_type": by_call_type,
        "pricing_assumptions": {
            "input_usd_per_m_tokens": INPUT_PER_M,
            "output_usd_per_m_tokens": OUTPUT_PER_M,
            "embed_usd_per_m_tokens": EMBED_PER_M,
            "model_inferred_from_call_type": True,
            "default_model": _DEFAULT_MODEL,
            "embed_model": _MODEL_MAP["embed"],
            "service_map": dict(_SERVICE_MAP),
        },
    }
