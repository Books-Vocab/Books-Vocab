"""Read-only backlog queries and filter composition.

This seam owns traversal, ordering, list filters, dispatch predicates, and the
re-verification queue.  Policy callbacks are injected from ``backlog.py`` so
the query layer does not import mutation, validation, or CLI code.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Callable, Pattern


@dataclass(frozen=True)
class QueryDeps:
    backlog_error: type[Exception]
    iter_entries_fn: Callable[[Path], object]
    sort_key_fn: Callable[[dict], tuple]
    brief_fields: tuple[str, ...]
    acceptance_green_expected: str
    date_re: Pattern[str]
    today: Callable[[], str]
    days_before: Callable[[str, int], str]
    held_tickets: Callable[[], dict]
    blocking_ids: Callable[[dict], list[str]]
    contract_preflight: Callable[..., list[dict]]
    worst_first_key: Callable[[dict], tuple]
    scope_status_fn: Callable[[object], str] | None = None


def iter_entries(store: Path):
    store = Path(store)
    if not store.exists():
        return
    for path in sorted(store.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict):
            yield payload


def sort_key(payload: dict) -> tuple:
    return (str(payload.get("date", "")), str(payload.get("id", "")))


def entry_sort_key_by_id(
    store: Path,
    *,
    iter_entries_fn: Callable[[Path], object] = iter_entries,
    sort_key_fn: Callable[[dict], tuple] = sort_key,
):
    index = {payload.get("id"): sort_key_fn(payload)
             for payload in iter_entries_fn(store)}
    return lambda entry_id: index.get(entry_id, ("", entry_id))


def list_entries(
    store: Path,
    *,
    deps: QueryDeps,
    status: str | None = None,
    stream: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    groomed: bool = False,
    ungroomed: bool = False,
    groom_stale_days: int | None = None,
    include_closed: bool = False,
    acceptance_manual: bool = False,
    acceptance_green_expected: bool = False,
    fixed_elsewhere: bool = False,
    missing_brief: bool = False,
    grep: str | None = None,
    dispatch: bool = False,
    held: dict | None = None,
    repo: Path | None = None,
) -> list[dict]:
    error = deps.backlog_error
    if groomed and ungroomed:
        raise error("--groomed and --ungroomed are mutually exclusive")
    if groom_stale_days is not None:
        if not ungroomed:
            raise error("--groom-stale-days only applies with --ungroomed")
        if groom_stale_days < 0:
            raise error("--groom-stale-days must be a non-negative integer")
    if dispatch:
        conflict = None
        if ungroomed:
            conflict = ("--ungroomed", "--dispatch only ever contains GROOMED entries")
        elif status in ("fixed", "wont-fix"):
            conflict = (f"--status {status}",
                        "--dispatch only ever contains UNRESOLVED entries")
        if conflict:
            flag, why = conflict
            raise error(
                f"{flag} and --dispatch are empty by construction: {why}. Drop one "
                f"— `--dispatch` for what to take next, `{flag}` on its own to look "
                f"at that set."
            )
    if include_closed and not ungroomed:
        raise error(
            "--include-closed only widens --ungroomed; it has no effect on its own. "
            "Drop it, or add `--ungroomed`."
        )
    if ungroomed and not include_closed and status in ("fixed", "wont-fix"):
        raise error(
            f"--ungroomed already excludes closed entries, so --status {status} is "
            f"empty by construction. Add `--include-closed` to inspect that closed "
            f"entry, or drop `--status {status}`."
        )
    open_ids = ({payload.get("id") for payload in deps.iter_entries_fn(store)
                 if payload.get("status") not in ("fixed", "wont-fix")}
                if dispatch else set())
    if missing_brief and status in ("fixed", "wont-fix"):
        raise error(
            f"--missing-brief already means UNRESOLVED, so --status {status} is "
            "empty by construction (a closed entry never reaches the board). "
            "Drop one: `--missing-brief` for the backfill queue, or "
            f"`--status {status}` on its own to look at closed entries."
        )

    wanted = {"status": status, "stream": stream, "severity": severity,
              "category": category}
    hits = [payload for payload in deps.iter_entries_fn(store)
            if all(value is None or payload.get(field) == value
                   for field, value in wanted.items())]
    if groomed:
        hits = [payload for payload in hits if payload.get("groomed_by")]
    if ungroomed:
        groom_cutoff = (
            deps.days_before(deps.today(), groom_stale_days)
            if groom_stale_days is not None else None
        )
        hits = [payload for payload in hits
                if (not payload.get("groomed_by")
                    or (groom_cutoff is not None
                        and deps.date_re.match(str(payload.get("groomed_at") or ""))
                        and str(payload["groomed_at"]) < groom_cutoff))
                and (include_closed
                     or payload.get("status") not in ("fixed", "wont-fix"))]
    if acceptance_manual:
        hits = [payload for payload in hits
                if str(payload.get("acceptance_manual") or "").strip()]
    if acceptance_green_expected:
        hits = [payload for payload in hits
                if str(payload.get(deps.acceptance_green_expected) or "").strip()]
    if fixed_elsewhere:
        hits = [payload for payload in hits
                if str(payload.get("fixed_elsewhere") or "").strip()]
    if missing_brief:
        def scope_is_known(payload: dict) -> bool:
            value = payload.get("scope")
            if deps.scope_status_fn is not None:
                return deps.scope_status_fn(value) == "known"
            return isinstance(value, dict)

        hits = [payload for payload in hits
                if payload.get("status") not in ("fixed", "wont-fix")
                and (
                    not str(payload.get("brief") or "").strip()
                    or ("scope" in deps.brief_fields and not scope_is_known(payload))
                )]
    if grep:
        try:
            pattern = re.compile(grep, re.IGNORECASE)
        except re.error as exc:
            raise error(f"--grep 不是合法的正規表示式: {exc}") from exc
        fields = ("detail", "resolution", "plan", "fix_site")
        hits = [payload for payload in hits
                if any(pattern.search(str(payload.get(field) or ""))
                       for field in fields)]
    if dispatch:
        claimed = deps.held_tickets() if held is None else held
        hits = [payload for payload in hits
                if str(payload.get("groomed_by") or "").strip()
                and payload.get("status") not in ("fixed", "wont-fix")
                and payload.get("id") not in claimed]
        hits = [payload for payload in hits
                if not any(blocker in open_ids
                           for blocker in deps.blocking_ids(payload))]
        hits = [payload for payload in hits
                if not deps.contract_preflight(payload, repo=repo)]
        return sorted(hits, key=deps.worst_first_key)
    return sorted(hits, key=deps.sort_key_fn)


def select_entries(
    store: Path,
    *,
    list_entries_fn: Callable[..., list[dict]],
    date_re: Pattern[str],
    days_before: Callable[[str, int], str],
    today: Callable[[], str],
    backlog_error: type[Exception],
    unverified: bool = False,
    stale_days: int | None = None,
    groom_stale_days: int | None = None,
    today_value: str | None = None,
    **filters,
) -> list[dict]:
    if unverified and stale_days is not None:
        raise backlog_error("--unverified and --stale are mutually exclusive")
    hits = list_entries_fn(store, groom_stale_days=groom_stale_days, **filters)
    if unverified:
        hits = [payload for payload in hits
                if not str(payload.get("verified_at") or "").strip()
                or not str(payload.get("verified_by") or "").strip()]
    if stale_days is not None:
        cutoff = days_before(today_value or today(), stale_days)
        hits = [payload for payload in hits
                if date_re.match(str(payload.get("verified_at") or ""))
                and payload["verified_at"] < cutoff]
    return hits
