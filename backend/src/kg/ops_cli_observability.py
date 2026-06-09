"""Time-series and observability commands for the readonly ops CLI."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kg.error_signals import JUDGE_AUTO_REJECT_WHERE, PIPELINE_FAILURE_WHERE
from kg.ops_shared import connect_ro, data_dir, emit_json, print_table, provider_column_expr, resolve_uid
from kg.quota_service import token_cost_usd

from .ops_cli_shared import _bucket_key_from_date, _cutoff_iso, _enumerate_buckets, _parse_day


def _count_by_day_ro(db_path: Path, table: str, ts_col: str, cutoff: str, *, where: str = "", count: str = "COUNT(*)") -> dict[str, int]:
    if not db_path.exists():
        return {}
    conn = connect_ro(db_path)
    try:
        rows = conn.execute(
            f"SELECT substr({ts_col},1,10) AS d, {count} FROM {table} "
            f"WHERE {ts_col} >= ?{where} GROUP BY d",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    return {d: int(c or 0) for d, c in rows if d}


def cmd_timeseries(args: argparse.Namespace) -> None:
    metric = args.metric
    bucket = args.bucket
    range_ = args.range
    from kg.admin_cost_summary import since_iso
    since = since_iso(range_)
    uid_filter = args.uid

    result: dict = {"metric": metric, "bucket": bucket, "range": range_, "since": since, "uid": uid_filter, "count": 0, "series": []}
    acc: dict[str, object] = {}
    min_dt = max_dt = None
    db_path = data_dir() / "token_usage.db"
    if db_path.exists():
        conn = connect_ro(db_path)
        pcol = provider_column_expr(conn)
        sql = f"SELECT user_id, call_type, {pcol} AS provider, input_tokens, output_tokens, created_at FROM token_usage"
        clauses: list[str] = []
        params: list = []
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)
        if uid_filter != "all":
            uid = resolve_uid(uid_filter, data_dir())
            result["uid"] = uid
            clauses.append("user_id = ?")
            params.append(uid)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = conn.execute(sql, params).fetchall()
        conn.close()

        for user_id, call_type, provider, t_in, t_out, created_at in rows:
            d = _parse_day(created_at)
            if d is None:
                continue
            key = _bucket_key_from_date(d, bucket)
            min_dt = d if min_dt is None or d < min_dt else min_dt
            max_dt = d if max_dt is None or d > max_dt else max_dt
            if metric == "cost":
                acc[key] = float(acc.get(key, 0.0)) + token_cost_usd(call_type, int(t_in or 0), int(t_out or 0), provider=provider)
            elif metric == "calls":
                acc[key] = int(acc.get(key, 0)) + 1
            else:
                acc.setdefault(key, set()).add(user_id)  # type: ignore[union-attr]

    observed: dict[str, float | int] = {}
    for key, val in acc.items():
        if metric == "active_users":
            observed[key] = len(val)  # type: ignore[arg-type]
        elif metric == "cost":
            observed[key] = round(float(val), 6)
        else:
            observed[key] = val  # type: ignore[assignment]

    zero: float | int = 0.0 if metric == "cost" else 0
    if args.fill_zero:
        start_d = (_parse_day(since) if since is not None else min_dt)
        if start_d is not None:
            end_d = datetime.now(UTC).date()
            if max_dt is not None and max_dt > end_d:
                end_d = max_dt
            series = [{"bucket": k, "value": observed.get(k, zero)} for k in _enumerate_buckets(start_d, end_d, bucket)]
        else:
            series = []
    else:
        series = [{"bucket": k, "value": observed[k]} for k in sorted(observed)]

    result["series"] = series
    result["count"] = len(series)
    if args.json:
        emit_json(result)
        return

    uid_label = "all users" if uid_filter == "all" else result["uid"]
    print(f"Timeseries — {metric} by {bucket}  |  {uid_label}  |  range={range_}")
    if not series:
        print("(no data)")
        return

    def _fmt(v: float | int) -> str:
        return f"${v:.6f}" if metric == "cost" else str(v)

    baseline = max((s["value"] for s in series), default=0)
    max_val = float(baseline)
    rows_out = []
    for s in series:
        bar = "█" * round((float(s["value"]) / max_val) * 24) if max_val else ""
        rows_out.append([s["bucket"], _fmt(s["value"]), bar])
    print_table(["Bucket", metric.capitalize(), "Trend"], rows_out)
    print(f"\n(trend bar 滿格 = {_fmt(baseline)})")


def cmd_trends(args: argparse.Namespace) -> None:
    window = max(1, min(args.window, 90))
    dd = data_dir()
    today = datetime.now(UTC).date()
    days = [(today - timedelta(days=window - 1 - i)).isoformat() for i in range(window)]
    cutoff = days[0]

    pipe_fail = _count_by_day_ro(dd / "pipeline_runs.db", "pipeline_runs", "started_at", cutoff, where=f" AND {PIPELINE_FAILURE_WHERE}")
    judge_rej = _count_by_day_ro(dd / "judge_log.db", "judge_log", "created_at", cutoff, where=f" AND {JUDGE_AUTO_REJECT_WHERE}")
    actives = _count_by_day_ro(dd / "token_usage.db", "token_usage", "created_at", cutoff, count="COUNT(DISTINCT user_id)")

    tokens_map: dict[str, int] = {}
    tdb = dd / "token_usage.db"
    if tdb.exists():
        conn = connect_ro(tdb)
        try:
            for d, ti, to in conn.execute(
                "SELECT substr(created_at,1,10) AS d, SUM(input_tokens), SUM(output_tokens) "
                "FROM token_usage WHERE created_at >= ? GROUP BY d",
                (cutoff,),
            ):
                if d:
                    tokens_map[d] = int(ti or 0) + int(to or 0)
        finally:
            conn.close()

    errors_per_day = [pipe_fail.get(d, 0) + judge_rej.get(d, 0) for d in days]
    active_users_per_day = [actives.get(d, 0) for d in days]
    tokens_per_day = [tokens_map.get(d, 0) for d in days]
    total_errors = sum(errors_per_day)

    llm_err_map: dict[str, int] = {}
    llm_db = dd / "llm_errors.db"
    if llm_db.exists():
        conn = connect_ro(llm_db)
        try:
            for d, c in conn.execute(
                "SELECT substr(created_at,1,10) AS d, COUNT(*) FROM llm_errors "
                "WHERE created_at >= ? GROUP BY d", (cutoff,)
            ):
                if d:
                    llm_err_map[d] = int(c or 0)
        finally:
            conn.close()
    llm_errors_per_day = [llm_err_map.get(d, 0) for d in days]
    total_llm_errors = sum(llm_errors_per_day)

    result = {
        "window_days": window,
        "days": days,
        "errors_per_day": errors_per_day,
        "llm_errors_per_day": llm_errors_per_day,
        "active_users_per_day": active_users_per_day,
        "tokens_per_day": tokens_per_day,
        "total_errors": total_errors,
        "total_llm_errors": total_llm_errors,
    }
    if args.json:
        emit_json(result)
        return

    print(f"Trends — last {window}d global monitoring (UTC)")
    print(f"Total errors (業務): {total_errors}  (failed pipeline + auto-judge rejects)")
    print(f"Total LLM failures (真火): {total_llm_errors}  (429/5xx/timeout)")
    print()
    max_err = max(errors_per_day) if errors_per_day else 0
    rows_out = []
    for d, e, le, a, tk in zip(days, errors_per_day, llm_errors_per_day, active_users_per_day, tokens_per_day, strict=True):
        bar = "█" * round((e / max_err) * 20) if max_err else ""
        rows_out.append([d, str(e), bar, str(le), str(a), str(tk)])
    print_table(["Date", "Errors", "Err Trend", "LLM-Fail", "Active", "Tokens"], rows_out)


def cmd_llm_errors(args: argparse.Namespace) -> None:
    window = max(1, min(args.window, 90))
    dd = data_dir()
    today = datetime.now(UTC).date()
    days = [(today - timedelta(days=window - 1 - i)).isoformat() for i in range(window)]
    cutoff = days[0]

    db_path = dd / "llm_errors.db"
    by_day: dict[str, int] = {}
    by_class: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    by_status: dict[str, int] = {}
    recent: list[dict] = []
    total = 0

    if db_path.exists():
        conn = connect_ro(db_path)
        try:
            uid_where = ""
            params: list = [cutoff]
            if args.uid != "all":
                uid_where = " AND user_id = ?"
                params.append(args.uid)
            for d, c in conn.execute(f"SELECT substr(created_at,1,10) AS d, COUNT(*) FROM llm_errors WHERE created_at >= ?{uid_where} GROUP BY d", tuple(params)):
                if d:
                    by_day[d] = int(c or 0)
            for ec, c in conn.execute(f"SELECT error_class, COUNT(*) FROM llm_errors WHERE created_at >= ?{uid_where} GROUP BY error_class", tuple(params)):
                by_class[ec] = int(c or 0)
            for prov, c in conn.execute(f"SELECT COALESCE(provider,'unknown'), COUNT(*) FROM llm_errors WHERE created_at >= ?{uid_where} GROUP BY provider", tuple(params)):
                by_provider[prov] = int(c or 0)
            for sc, c in conn.execute(f"SELECT COALESCE(CAST(status_code AS TEXT),'none'), COUNT(*) FROM llm_errors WHERE created_at >= ?{uid_where} GROUP BY status_code", tuple(params)):
                by_status[sc] = int(c or 0)
            limit = 10
            for row in conn.execute(
                f"SELECT user_id, call_type, provider, model, error_class, status_code, "
                f"message, substr(created_at,1,19) AS ts FROM llm_errors "
                f"WHERE created_at >= ?{uid_where} ORDER BY created_at DESC LIMIT ?",
                tuple(params + [limit]),
            ):
                recent.append({
                    "user_id": row[0],
                    "call_type": row[1],
                    "provider": row[2],
                    "model": row[3],
                    "error_class": row[4],
                    "status_code": row[5],
                    "message": row[6],
                    "created_at": row[7],
                })
            total = sum(by_day.values())
        finally:
            conn.close()

    per_day = [by_day.get(d, 0) for d in days]
    result = {
        "window_days": window,
        "total": total,
        "by_day": {d: by_day.get(d, 0) for d in days},
        "by_class": by_class,
        "by_provider": by_provider,
        "by_status": by_status,
        "recent": recent,
    }
    if args.json:
        emit_json(result)
        return

    print(f"LLM Errors (真火) — last {window}d")
    print(f"Total: {total}")
    print()
    max_val = max(per_day) if per_day else 0
    rows_out = []
    for d, v in zip(days, per_day, strict=True):
        bar = "█" * round((v / max_val) * 20) if max_val else ""
        rows_out.append([d, str(v), bar])
    print_table(["Date", "Count", "Trend"], rows_out)
    print()
    if by_class:
        print("By error class:")
        print_table(["Class", "Count"], [[k, str(v)] for k, v in sorted(by_class.items(), key=lambda x: -x[1])[:5]])
        print()
    if by_provider:
        print("By provider:")
        print_table(["Provider", "Count"], [[k, str(v)] for k, v in sorted(by_provider.items(), key=lambda x: -x[1])[:5]])
        print()
    if by_status:
        print("By status code:")
        print_table(["Status", "Count"], [[k, str(v)] for k, v in sorted(by_status.items(), key=lambda x: -x[1])[:5]])
        print()
    if recent:
        print(f"Recent {len(recent)} errors:")
        for r in recent:
            sc = f" [{r['status_code']}]" if r["status_code"] is not None else ""
            print(f"  {r['created_at']} {r['error_class']}{sc} — {r['call_type']} (uid={r['user_id']}, provider={r['provider'] or 'unknown'})")
