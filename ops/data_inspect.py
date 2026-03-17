#!/usr/bin/env python3
"""KG data inspector — observe card/graph/pipeline quality from local DB.

Usage:
    python ops/data_inspect.py                  # overview for default user
    python ops/data_inspect.py -u chen overview  # explicit user
    python ops/data_inspect.py sample 15        # random card sample (default 10)
    python ops/data_inspect.py gaps             # cards missing enrichment
    python ops/data_inspect.py graph            # graph links + candidates
    python ops/data_inspect.py notes            # note quality deep-dive
    python ops/data_inspect.py search <keyword> # search cards by content/meaning
    python ops/data_inspect.py card <id>        # single card full dump
    python ops/data_inspect.py sql "SELECT ..."  # raw SQL on cards.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "backend" / "data" / "users"


# ── helpers ──────────────────────────────────────────────────────────────

def _conn(user: str) -> sqlite3.Connection:
    db = DATA / user / "cards.db"
    if not db.exists():
        sys.exit(f"✗ DB not found: {db}")
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    return c


def _cols(conn: sqlite3.Connection) -> list[str]:
    return [r[1] for r in conn.execute("PRAGMA table_info(card)").fetchall()]


def _card_select(conn: sqlite3.Connection) -> str:
    """Build SELECT with only columns that exist in the DB."""
    cols = _cols(conn)
    want = ["id", "content", "meaning", "pos", "note", "difficulty",
            "examples", "collocations", "mode", "root_form",
            "inflections", "is_deleted", "is_archived", "created_at", "updated_at",
            "review_interval_hours", "next_review_at", "last_reviewed_at",
            "review_count", "lapse_count", "review_streak", "last_review_feedback"]
    return ", ".join(c for c in want if c in cols)


def _json_col(row, col: str) -> list:
    v = row[col] if col in row.keys() else None
    if not v:
        return []
    return json.loads(v) if isinstance(v, str) else v


def _graph_path(user: str) -> Path:
    return DATA / user / "graph.json"


def _candidates_path(user: str) -> Path:
    return DATA / user / "candidates.json"


def _print_card(row, verbose: bool = False):
    print(f"\n{'─'*60}")
    print(f"  id: {row['id']}   content: {row['content']}")
    print(f"  meaning: {row['meaning']}")
    cols = row.keys()
    if "pos" in cols:
        print(f"  pos: {row['pos'] or '∅'}")
    if "note" in cols:
        note = row["note"]
        if note:
            display = note if verbose else (note[:120] + "…" if len(note) > 120 else note)
            print(f"  note: {display}")
        else:
            print(f"  note: ∅")
    if "difficulty" in cols:
        d = row["difficulty"]
        tier = "∅"
        if d is not None:
            if d >= 3.44:
                tier = f"{d} (core)"
            elif d >= 3.01:
                tier = f"{d} (intermediate)"
            elif d >= 2.55:
                tier = f"{d} (advanced)"
            else:
                tier = f"{d} (rare)"
        print(f"  difficulty: {tier}")
    exs = _json_col(row, "examples")
    if exs:
        print(f"  examples ({len(exs)}): {exs[0][:80]}{'…' if len(exs[0])>80 else ''}")
    colls = _json_col(row, "collocations")
    if colls:
        print(f"  collocations: {colls[:4]}")
    if verbose:
        for extra in ["mode", "root_form", "review_count",
                       "lapse_count", "review_streak", "created_at"]:
            if extra in cols and row[extra] is not None:
                print(f"  {extra}: {row[extra]}")


def _section(title: str):
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


# ── commands ─────────────────────────────────────────────────────────────

def cmd_overview(user: str, **_):
    conn = _conn(user)
    total = conn.execute("SELECT COUNT(*) FROM card WHERE is_deleted=0").fetchone()[0]
    deleted = conn.execute("SELECT COUNT(*) FROM card WHERE is_deleted=1").fetchone()[0]

    _section(f"Overview — user: {user} ({total} active, {deleted} deleted)")

    # enrichment coverage
    cols = _cols(conn)
    has_pos = conn.execute("SELECT COUNT(*) FROM card WHERE is_deleted=0 AND pos IS NOT NULL").fetchone()[0]
    has_note = conn.execute("SELECT COUNT(*) FROM card WHERE is_deleted=0 AND note IS NOT NULL").fetchone()[0]
    has_diff = conn.execute("SELECT COUNT(*) FROM card WHERE is_deleted=0 AND difficulty IS NOT NULL").fetchone()[0]
    print(f"\n[Enrichment Coverage]")
    print(f"  pos:        {has_pos}/{total} ({100*has_pos//total}%)")
    print(f"  note:       {has_note}/{total} ({100*has_note//total}%)")
    print(f"  difficulty: {has_diff}/{total} ({100*has_diff//total}%)")

    # difficulty distribution
    print(f"\n[Difficulty Distribution]")
    for label, lo, hi in [("core ≥3.44", 3.44, 99), ("intermediate", 3.01, 3.44),
                           ("advanced", 2.55, 3.01), ("rare <2.55", 0, 2.55)]:
        cnt = conn.execute("SELECT COUNT(*) FROM card WHERE is_deleted=0 AND difficulty>=? AND difficulty<?",
                           (lo, hi)).fetchone()[0]
        bar = "█" * (cnt // 2)
        print(f"  {label:16s} {cnt:4d}  {bar}")
    null_d = total - has_diff
    if null_d:
        print(f"  {'NULL':16s} {null_d:4d}")

    # note length stats
    if has_note:
        lengths = [r[0] for r in conn.execute(
            "SELECT LENGTH(note) FROM card WHERE is_deleted=0 AND note IS NOT NULL ORDER BY LENGTH(note)"
        ).fetchall()]
        print(f"\n[Note Length]")
        print(f"  min={lengths[0]}  median={lengths[len(lengths)//2]}  max={lengths[-1]}  avg={sum(lengths)//len(lengths)}")

    # examples/collocations coverage
    if "examples" in cols:
        has_ex = conn.execute(
            "SELECT COUNT(*) FROM card WHERE is_deleted=0 AND examples IS NOT NULL AND examples != '[]'"
        ).fetchone()[0]
        print(f"\n[Examples]  {has_ex}/{total} cards have examples")
    if "collocations" in cols:
        has_coll = conn.execute(
            "SELECT COUNT(*) FROM card WHERE is_deleted=0 AND collocations IS NOT NULL AND collocations != '[]'"
        ).fetchone()[0]
        print(f"[Collocations]  {has_coll}/{total} cards have collocations")

    # graph summary
    gp = _graph_path(user)
    if gp.exists():
        data = json.loads(gp.read_text())
        links = data if isinstance(data, list) else data.get("links", [])
        kinds = {}
        for lk in links:
            kinds[lk["kind"]] = kinds.get(lk["kind"], 0) + 1
        print(f"\n[Graph]  {len(links)} links  {kinds}")
    cp = _candidates_path(user)
    if cp.exists():
        cands = json.loads(cp.read_text())
        print(f"[Candidates]  {len(cands)} pending")

    # review stats (column may not exist)
    if "review_count" in cols:
        reviewed = conn.execute("SELECT COUNT(*) FROM card WHERE is_deleted=0 AND review_count>0").fetchone()[0]
        print(f"\n[Review]  {reviewed}/{total} cards reviewed at least once")

    conn.close()


def cmd_sample(user: str, n: int = 10, **_):
    conn = _conn(user)
    sel = _card_select(conn)
    rows = conn.execute(f"SELECT {sel} FROM card WHERE is_deleted=0 ORDER BY RANDOM() LIMIT ?", (n,)).fetchall()
    _section(f"Random Sample — {len(rows)} cards")
    for r in rows:
        _print_card(r)
    conn.close()


def cmd_gaps(user: str, **_):
    conn = _conn(user)
    _section("Gaps — cards missing enrichment")

    no_pos = conn.execute(
        "SELECT id, content, meaning FROM card WHERE is_deleted=0 AND pos IS NULL"
    ).fetchall()
    print(f"\n[Missing POS] {len(no_pos)} cards")
    for r in no_pos[:20]:
        print(f"  {r['id']}  {r['content']}: {r['meaning'][:50]}")

    no_note = conn.execute(
        "SELECT id, content, meaning FROM card WHERE is_deleted=0 AND note IS NULL"
    ).fetchall()
    print(f"\n[Missing Note] {len(no_note)} cards")
    for r in no_note[:20]:
        print(f"  {r['id']}  {r['content']}: {r['meaning'][:50]}")

    no_diff = conn.execute(
        "SELECT id, content, meaning FROM card WHERE is_deleted=0 AND difficulty IS NULL"
    ).fetchall()
    print(f"\n[Missing Difficulty] {len(no_diff)} cards")
    for r in no_diff[:20]:
        print(f"  {r['id']}  {r['content']}: {r['meaning'][:50]}")

    cols = _cols(conn)
    if "examples" in cols:
        no_ex = conn.execute(
            "SELECT id, content FROM card WHERE is_deleted=0 AND (examples IS NULL OR examples = '[]')"
        ).fetchall()
        print(f"\n[Missing Examples] {len(no_ex)} cards")
        for r in no_ex[:10]:
            print(f"  {r['id']}  {r['content']}")

    conn.close()


def cmd_graph(user: str, **_):
    conn = _conn(user)
    _section("Graph Links")

    gp = _graph_path(user)
    if not gp.exists():
        print("  No graph.json found.")
        return

    data = json.loads(gp.read_text())
    links = data if isinstance(data, list) else data.get("links", [])

    # stats
    kinds = {}
    confs = []
    for lk in links:
        kinds[lk["kind"]] = kinds.get(lk["kind"], 0) + 1
        confs.append(lk.get("confidence", 0))

    print(f"  Total: {len(links)}")
    print(f"  By kind: {kinds}")
    if confs:
        confs.sort()
        print(f"  Confidence: min={confs[0]:.2f}  median={confs[len(confs)//2]:.2f}  max={confs[-1]:.2f}")

    # list all
    print()
    for lk in links:
        fc = conn.execute("SELECT content FROM card WHERE id=?", (lk["from_id"],)).fetchone()
        tc = conn.execute("SELECT content FROM card WHERE id=?", (lk["to_id"],)).fetchone()
        fn = fc[0] if fc else "?"
        tn = tc[0] if tc else "?"
        reason = lk.get("reason", "")[:65]
        print(f"  {fn} <-> {tn}  | {lk['kind']}  conf={lk.get('confidence','?')}  | {reason}")

    # candidates
    cp = _candidates_path(user)
    if cp.exists():
        cands = json.loads(cp.read_text())
        if cands:
            print(f"\n  Pending candidates: {len(cands)}")
            for c in cands[:10]:
                fc = conn.execute("SELECT content FROM card WHERE id=?", (c["from_id"],)).fetchone()
                tc = conn.execute("SELECT content FROM card WHERE id=?", (c["to_id"],)).fetchone()
                fn = fc[0] if fc else "?"
                tn = tc[0] if tc else "?"
                print(f"    {fn} <-> {tn}  sim={c.get('similarity','?')}")

    conn.close()


def cmd_notes(user: str, **_):
    conn = _conn(user)
    sel = _card_select(conn)
    _section("Note Quality Deep-dive")

    # shortest notes
    rows = conn.execute(
        f"SELECT {sel} FROM card WHERE is_deleted=0 AND note IS NOT NULL ORDER BY LENGTH(note) LIMIT 5"
    ).fetchall()
    print("\n[Shortest Notes]")
    for r in rows:
        _print_card(r, verbose=True)

    # longest notes
    rows = conn.execute(
        f"SELECT {sel} FROM card WHERE is_deleted=0 AND note IS NOT NULL ORDER BY LENGTH(note) DESC LIMIT 5"
    ).fetchall()
    print("\n[Longest Notes]")
    for r in rows:
        _print_card(r, verbose=True)

    # notes that look low quality (very short or no Chinese)
    rows = conn.execute(
        f"SELECT {sel} FROM card WHERE is_deleted=0 AND note IS NOT NULL AND LENGTH(note) < 40"
    ).fetchall()
    if rows:
        print(f"\n[Suspiciously Short Notes (<40 chars)] {len(rows)} cards")
        for r in rows:
            _print_card(r)

    conn.close()


def cmd_search(user: str, keyword: str = "", **_):
    if not keyword:
        sys.exit("usage: data_inspect.py search <keyword>")
    conn = _conn(user)
    sel = _card_select(conn)
    rows = conn.execute(
        f"SELECT {sel} FROM card WHERE is_deleted=0 AND (content LIKE ? OR meaning LIKE ? OR note LIKE ?)",
        (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%")
    ).fetchall()
    _section(f"Search '{keyword}' — {len(rows)} matches")
    for r in rows:
        _print_card(r, verbose=True)
    conn.close()


def cmd_card(user: str, card_id: str = "", **_):
    if not card_id:
        sys.exit("usage: data_inspect.py card <id>")
    conn = _conn(user)
    sel = _card_select(conn)
    row = conn.execute(f"SELECT {sel} FROM card WHERE id=?", (card_id,)).fetchone()
    if not row:
        sys.exit(f"✗ Card {card_id} not found")
    _section(f"Card {card_id}")
    _print_card(row, verbose=True)

    # show graph links involving this card
    gp = _graph_path(user)
    if gp.exists():
        data = json.loads(gp.read_text())
        links = data if isinstance(data, list) else data.get("links", [])
        related = [lk for lk in links if lk["from_id"] == card_id or lk["to_id"] == card_id]
        if related:
            print(f"\n  [Graph Links] {len(related)}")
            for lk in related:
                other_id = lk["to_id"] if lk["from_id"] == card_id else lk["from_id"]
                oc = conn.execute("SELECT content FROM card WHERE id=?", (other_id,)).fetchone()
                on = oc[0] if oc else "?"
                print(f"    <-> {on}  | {lk['kind']}  conf={lk.get('confidence','?')}")
    conn.close()


def cmd_sql(user: str, query: str = "", **_):
    if not query:
        sys.exit("usage: data_inspect.py sql \"SELECT ...\"")
    conn = _conn(user)
    try:
        rows = conn.execute(query).fetchall()
    except sqlite3.Error as e:
        sys.exit(f"✗ SQL error: {e}")
    if not rows:
        print("(no results)")
        return
    cols = rows[0].keys()
    print("  ".join(cols))
    print("─" * 60)
    for r in rows:
        print("  ".join(str(r[c]) for c in cols))
    conn.close()


# ── main ─────────────────────────────────────────────────────────────────

COMMANDS = {
    "overview": cmd_overview,
    "sample": cmd_sample,
    "gaps": cmd_gaps,
    "graph": cmd_graph,
    "notes": cmd_notes,
    "search": cmd_search,
    "card": cmd_card,
    "sql": cmd_sql,
}


def main():
    parser = argparse.ArgumentParser(description="KG data inspector")
    parser.add_argument("-u", "--user", default="chen", help="user directory name (default: chen)")
    parser.add_argument("command", nargs="?", default="overview", choices=list(COMMANDS.keys()),
                        help="inspection command (default: overview)")
    parser.add_argument("args", nargs="*", help="command-specific arguments")
    parsed = parser.parse_args()

    cmd_fn = COMMANDS[parsed.command]
    extra = parsed.args

    # dispatch with positional args
    if parsed.command == "sample":
        cmd_fn(parsed.user, n=int(extra[0]) if extra else 10)
    elif parsed.command == "search":
        cmd_fn(parsed.user, keyword=extra[0] if extra else "")
    elif parsed.command == "card":
        cmd_fn(parsed.user, card_id=extra[0] if extra else "")
    elif parsed.command == "sql":
        cmd_fn(parsed.user, query=" ".join(extra) if extra else "")
    else:
        cmd_fn(parsed.user)


if __name__ == "__main__":
    main()
