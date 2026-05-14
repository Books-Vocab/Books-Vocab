"""Data consistency scanner — find orphan rows / dangling references.

Five categories:
  1. cards.notebook_id → notebooks.id missing
  2. graph_links {from_id,to_id} → cards.id missing
  3. translate_log.user_id → users.json key missing
  4. judge_log {from_id,to_id} → cards.id missing (per user, per notebook)
  5. token_usage.user_id → users.json key missing

CLI:
    uv run python -m kg.orphan_scan --report                 # list + counts
    uv run python -m kg.orphan_scan --fix --dry-run          # preview deletions
    uv run python -m kg.orphan_scan --fix --confirm          # actually clean

The admin endpoint at ``GET /api/admin/orphans/scan`` is read-only and
exposes :func:`scan` results.

Fix policy:
  - Orphan card → set ``is_deleted = 1`` (soft delete, recoverable).
  - Orphan graph link → strip entry from JSON via atomic write.
  - Orphan translate_log / judge_log / token_usage rows → hard DELETE.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_user_ids(data_dir: Path) -> set[str]:
    """Read users.json and return the set of real user ids (skip ``_meta``)."""
    users_file = data_dir / "users.json"
    if not users_file.exists():
        return set()
    try:
        payload = json.loads(users_file.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not parse %s", users_file)
        return set()
    return {k for k in payload.keys() if isinstance(k, str) and not k.startswith("_")}


def _iter_user_dirs(data_dir: Path, known_users: set[str]) -> list[tuple[str, Path]]:
    """List (user_id, user_dir) for every users/<uid> directory that maps to
    a real user.  Directories without a matching users.json entry are skipped
    (they are themselves orphans, but cleaning them up is outside this scope)."""
    users_root = data_dir / "users"
    if not users_root.exists():
        return []
    out: list[tuple[str, Path]] = []
    for entry in users_root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name in known_users:
            out.append((entry.name, entry))
    return out


def _live_cards(cards_db: Path) -> dict[str, str]:
    """Return ``{card_id: notebook_id}`` for non-deleted cards.  Missing db
    returns empty dict.  Used both for orphan detection and for the
    valid-card set on graph/judge orphan checks."""
    if not cards_db.exists():
        return {}
    with sqlite3.connect(str(cards_db)) as conn:
        rows = conn.execute(
            "SELECT id, notebook_id FROM card WHERE is_deleted = 0"
        ).fetchall()
    return {row[0]: row[1] for row in rows}


def _all_cards_with_state(cards_db: Path) -> list[tuple[str, str, int]]:
    """Return ``[(card_id, notebook_id, is_deleted), ...]`` — full set."""
    if not cards_db.exists():
        return []
    with sqlite3.connect(str(cards_db)) as conn:
        return conn.execute(
            "SELECT id, notebook_id, is_deleted FROM card"
        ).fetchall()


def _live_notebook_ids(nb_db: Path) -> set[str]:
    """Return the set of notebook ids that exist (incl. soft-deleted).

    Soft-deleted notebooks still count as 'existing' for the cards→notebook
    orphan check — only fully-missing rows are flagged."""
    if not nb_db.exists():
        return set()
    with sqlite3.connect(str(nb_db)) as conn:
        rows = conn.execute("SELECT id FROM notebook").fetchall()
    return {row[0] for row in rows}


def _list_graph_files(user_dir: Path) -> list[tuple[str, Path]]:
    """Return ``[(notebook_id, graph_path), ...]``."""
    out: list[tuple[str, Path]] = []
    for path in user_dir.glob("graph_*.json"):
        nb_id = path.stem[len("graph_"):]
        if not nb_id:
            continue
        out.append((nb_id, path))
    return out


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write ``data`` to ``path`` atomically.

    Sequence: write tmp → fsync(tmp) → backup existing → os.replace(tmp, path).
    ``os.replace`` is the POSIX-atomic rename primitive; ``Path.replace`` wraps
    it but we use ``os.replace`` directly with string paths to keep the
    semantics obvious. fsync ensures the tmp payload is on disk before rename
    so a crash can't leave a half-written file under ``path``.
    """
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    tmp.write_text(payload)
    # Flush payload to disk before rename — without this a power loss between
    # rename and writeback can leave ``path`` pointing at zero-byte content.
    fd = os.open(str(tmp), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    if path.exists():
        os.replace(str(path), str(path.with_suffix(".json.bak")))
    os.replace(str(tmp), str(path))


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def scan(*, data_dir: Path) -> dict[str, Any]:
    """Read-only scan; returns a structured report.

    Shape::

        {
          "cards_orphan_notebook":      {"count": N, "items": [...]},
          "graph_links_orphan_card":    {"count": N, "items": [...]},
          "translate_log_orphan_user":  {"count": N, "items": [...]},
          "judge_log_orphan_card":      {"count": N, "items": [...]},
          "token_usage_orphan_user":    {"count": N, "items": [...]},
          "total": int,
        }
    """
    data_dir = Path(data_dir)
    user_ids = _load_user_ids(data_dir)
    user_dirs = _iter_user_dirs(data_dir, user_ids)

    cards_orphan: list[dict[str, Any]] = []
    graph_orphan: list[dict[str, Any]] = []
    judge_orphan: list[dict[str, Any]] = []

    for uid, udir in user_dirs:
        cards_db = udir / "cards.db"
        nb_db = udir / "notebooks.db"
        live_card_ids = set(_live_cards(cards_db).keys())
        nb_ids = _live_notebook_ids(nb_db)

        # 1. cards → notebook
        for cid, nb_id, is_deleted in _all_cards_with_state(cards_db):
            if is_deleted:
                continue
            if nb_id not in nb_ids:
                cards_orphan.append({
                    "user_id": uid,
                    "card_id": cid,
                    "notebook_id": nb_id,
                })

        # 2. graph_links → cards (per notebook)
        for nb_id, graph_path in _list_graph_files(udir):
            try:
                links = json.loads(graph_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(links, list):
                continue
            for lk in links:
                if not isinstance(lk, dict):
                    continue
                missing = []
                from_id = lk.get("from_id")
                to_id = lk.get("to_id")
                if from_id and from_id not in live_card_ids:
                    missing.append(from_id)
                if to_id and to_id not in live_card_ids:
                    missing.append(to_id)
                if missing:
                    graph_orphan.append({
                        "user_id": uid,
                        "notebook_id": nb_id,
                        "link_id": lk.get("id"),
                        "from_id": from_id,
                        "to_id": to_id,
                        "missing": missing,
                    })

    # Build a global per-user live-cards index for judge_log scan.
    user_live_cards: dict[str, set[str]] = {}
    for uid, udir in user_dirs:
        user_live_cards[uid] = set(_live_cards(udir / "cards.db").keys())

    # 4. judge_log
    judge_db = data_dir / "judge_log.db"
    if judge_db.exists():
        with sqlite3.connect(str(judge_db)) as conn:
            try:
                rows = conn.execute(
                    "SELECT id, user_id, notebook_id, from_id, to_id "
                    "FROM judge_log"
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        for row_id, uid, nb_id, from_id, to_id in rows:
            live = user_live_cards.get(uid)
            if live is None:
                # judge_log row for a user we don't know — covered by the
                # user-orphan category indirectly; flag both endpoints.
                judge_orphan.append({
                    "id": row_id,
                    "user_id": uid,
                    "notebook_id": nb_id,
                    "from_id": from_id,
                    "to_id": to_id,
                    "missing": [from_id, to_id],
                })
                continue
            missing = [c for c in (from_id, to_id) if c and c not in live]
            if missing:
                judge_orphan.append({
                    "id": row_id,
                    "user_id": uid,
                    "notebook_id": nb_id,
                    "from_id": from_id,
                    "to_id": to_id,
                    "missing": missing,
                })

    # 3. translate_log → user
    translate_orphan: list[dict[str, Any]] = []
    translate_db = data_dir / "translate_log.db"
    if translate_db.exists():
        with sqlite3.connect(str(translate_db)) as conn:
            try:
                rows = conn.execute(
                    "SELECT user_id, COUNT(*) FROM translate_log GROUP BY user_id"
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        for uid, count in rows:
            if uid and uid not in user_ids:
                translate_orphan.append({"user_id": uid, "rows": count})

    # 5. token_usage → user
    token_orphan: list[dict[str, Any]] = []
    token_db = data_dir / "token_usage.db"
    if token_db.exists():
        with sqlite3.connect(str(token_db)) as conn:
            try:
                rows = conn.execute(
                    "SELECT user_id, COUNT(*) FROM token_usage GROUP BY user_id"
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        for uid, count in rows:
            if uid and uid not in user_ids:
                token_orphan.append({"user_id": uid, "rows": count})

    report = {
        "cards_orphan_notebook": {"count": len(cards_orphan), "items": cards_orphan},
        "graph_links_orphan_card": {"count": len(graph_orphan), "items": graph_orphan},
        "translate_log_orphan_user": {
            "count": len(translate_orphan), "items": translate_orphan,
        },
        "judge_log_orphan_card": {"count": len(judge_orphan), "items": judge_orphan},
        "token_usage_orphan_user": {"count": len(token_orphan), "items": token_orphan},
    }
    report["total"] = sum(report[k]["count"] for k in report if k != "total")
    return report


# ---------------------------------------------------------------------------
# Fix
# ---------------------------------------------------------------------------

def fix(
    *,
    data_dir: Path,
    confirm: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Remove or soft-delete every orphan returned by :func:`scan`.

    Safety:
      - ``confirm`` must be ``True`` (raises ``ValueError`` otherwise).
      - ``dry_run=True`` reports counts without mutating anything.

    Operational notes:
      - **Run during backend downtime or a low-traffic window.** This function
        rewrites ``graph_*.json`` files and issues bulk SQLite ``DELETE`` /
        ``UPDATE`` against ``cards.db``, ``judge_log.db``, ``translate_log.db``
        and ``token_usage.db``. There is no app-level cross-file lock around
        the multi-step rewrite, so concurrent writers can race with us.
      - **If the caller holds an existing graph_links / cards lock, invoke
        ``fix()`` while still holding it** — pass-through is the safest way to
        guarantee the graph file we read in :func:`scan` is the same one we
        rewrite here. Otherwise prefer to quiesce the API (or stop the
        container) before calling.
    """
    if not confirm:
        raise ValueError(
            "orphan_scan.fix(): refusing to run without explicit confirm=True"
        )

    report = scan(data_dir=data_dir)
    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "cards_orphan_notebook": {
            "would_delete": report["cards_orphan_notebook"]["count"],
        },
        "graph_links_orphan_card": {
            "would_delete": report["graph_links_orphan_card"]["count"],
        },
        "translate_log_orphan_user": {
            "would_delete": sum(
                it.get("rows", 0)
                for it in report["translate_log_orphan_user"]["items"]
            ) or report["translate_log_orphan_user"]["count"],
        },
        "judge_log_orphan_card": {
            "would_delete": report["judge_log_orphan_card"]["count"],
        },
        "token_usage_orphan_user": {
            "would_delete": sum(
                it.get("rows", 0)
                for it in report["token_usage_orphan_user"]["items"]
            ) or report["token_usage_orphan_user"]["count"],
        },
    }
    summary["total_deleted"] = report["total"]

    if dry_run:
        return summary

    # --- mutate ---
    user_ids = _load_user_ids(data_dir)

    # 1. soft-delete orphan cards
    cards_by_user: dict[str, list[str]] = {}
    for item in report["cards_orphan_notebook"]["items"]:
        cards_by_user.setdefault(item["user_id"], []).append(item["card_id"])
    for uid, card_ids in cards_by_user.items():
        cards_db = data_dir / "users" / uid / "cards.db"
        if not cards_db.exists():
            continue
        with sqlite3.connect(str(cards_db)) as conn:
            conn.executemany(
                "UPDATE card SET is_deleted = 1 WHERE id = ?",
                [(cid,) for cid in card_ids],
            )
            conn.commit()

    # 2. strip orphan graph links — group by (user, notebook) file
    graph_by_file: dict[tuple[str, str], set[str]] = {}
    for item in report["graph_links_orphan_card"]["items"]:
        key = (item["user_id"], item["notebook_id"])
        link_id = item.get("link_id")
        if link_id is not None:
            graph_by_file.setdefault(key, set()).add(link_id)
    for (uid, nb_id), bad_link_ids in graph_by_file.items():
        graph_path = data_dir / "users" / uid / f"graph_{nb_id}.json"
        if not graph_path.exists():
            continue
        try:
            links = json.loads(graph_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(links, list):
            continue
        kept = [lk for lk in links if lk.get("id") not in bad_link_ids]
        _atomic_write_json(graph_path, kept)

    # 3. delete translate_log rows for ghost users
    ghost_users_t = [
        it["user_id"] for it in report["translate_log_orphan_user"]["items"]
    ]
    if ghost_users_t:
        translate_db = data_dir / "translate_log.db"
        if translate_db.exists():
            # Use the module singleton so any other live readers see the change.
            from . import translate_log as tl
            with tl._lock:
                conn = tl._get_conn()
                conn.executemany(
                    "DELETE FROM translate_log WHERE user_id = ?",
                    [(uid,) for uid in ghost_users_t],
                )
                conn.commit()

    # 4. delete judge_log rows
    judge_ids = [it["id"] for it in report["judge_log_orphan_card"]["items"]]
    if judge_ids:
        from . import judge_log as jl
        with jl._lock:
            conn = jl._get_conn()
            conn.executemany(
                "DELETE FROM judge_log WHERE id = ?",
                [(rid,) for rid in judge_ids],
            )
            conn.commit()

    # 5. delete token_usage rows
    ghost_users_tok = [
        it["user_id"] for it in report["token_usage_orphan_user"]["items"]
    ]
    if ghost_users_tok:
        from . import token_tracker as tt
        with tt._lock:
            conn = tt._get_conn()
            conn.executemany(
                "DELETE FROM token_usage WHERE user_id = ?",
                [(uid,) for uid in ghost_users_tok],
            )
            conn.commit()

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_data_dir() -> Path:
    from .settings import load_settings
    return load_settings().data_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kg.orphan_scan",
        description="Scan KG data for orphan rows; optionally clean them up.",
    )
    # --report and --fix are the two mutually-exclusive actions. One must be
    # specified explicitly — there is no implicit default, so an accidental
    # bare invocation prints help and exits non-zero instead of silently
    # running a scan.
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--report", action="store_true",
        help="Print the orphan scan report and exit.",
    )
    action.add_argument(
        "--fix", action="store_true",
        help="Run the fixer.  Requires --confirm to actually mutate; "
             "without --confirm, runs in dry-run mode.",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Acknowledge that --fix will mutate data.  Without this flag, "
             "--fix is forced into dry-run mode.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="With --fix, show what would be deleted without changing anything.",
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="Override data directory (defaults to KGSettings.data_dir).",
    )
    args = parser.parse_args(argv)

    if not (args.report or args.fix):
        parser.print_help(sys.stderr)
        print(
            "\nerror: one of --report or --fix is required.",
            file=sys.stderr,
        )
        return 2

    data_dir = Path(args.data_dir) if args.data_dir else _resolve_data_dir()

    if args.fix:
        # Without --confirm we force dry-run + warn loudly.
        dry_run = args.dry_run or not args.confirm
        if not args.confirm:
            print(
                "WARN: --fix without --confirm — running in dry-run mode. "
                "Re-run with --confirm to actually mutate."
            )
        summary = fix(data_dir=data_dir, confirm=True, dry_run=dry_run)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    # args.report is True (mutex group guarantees this branch).
    report = scan(data_dir=data_dir)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
