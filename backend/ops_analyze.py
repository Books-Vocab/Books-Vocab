#!/usr/bin/env python3
"""KG 用戶資料與知識圖譜深度分析工具。

部署在 container 內，透過 ops-cli 呼叫：
    ./ops/devops_kg_safe.sh ops-cli analyze <uid> [level]

Levels:
    1  快速健檢（額度 + 卡片數）
    2  額度消耗分析（call_type 佔比、拒絕率）
    3  圖譜拓撲（度數分布、連通分量、聚類係數）
    4  連結品質（confidence、kind、hub 偵測）
    5  嵌入分析 + 閾值掃描
    6  異常偵測（7 種問題類型）
    all  全部（預設）
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(os.getenv("KG_DATA_DIR", str(Path(__file__).resolve().parent / "data")))

# ── 定價常數 ──────────────────────────────────────────────
INPUT_PER_M = 0.10
OUTPUT_PER_M = 0.40
EMBED_PER_M = 0.00025


def _cost(call_type: str, inp: int, out: int) -> float:
    if call_type == "embed":
        return inp / 1_000_000 * EMBED_PER_M
    return inp / 1_000_000 * INPUT_PER_M + out / 1_000_000 * OUTPUT_PER_M


def _resolve_uid(partial: str) -> str:
    users_dir = DATA_DIR / "users"
    if not users_dir.exists():
        return partial
    if (users_dir / partial).exists():
        return partial
    matches = [d.name for d in users_dir.iterdir() if d.is_dir() and partial in d.name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"多個用戶匹配 '{partial}'：", file=sys.stderr)
        for m in matches:
            print(f"  {m}", file=sys.stderr)
        sys.exit(1)
    return partial


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _bar(n: int, max_width: int = 40) -> str:
    return "#" * min(n, max_width)


# ── Level 1: 快速健檢 ────────────────────────────────────────

def level_1(uid: str, udir: Path) -> None:
    _section("Level 1: 快速健檢")

    # 額度
    token_db = DATA_DIR / "token_usage.db"
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    pro_limit = float(os.getenv("PRO_DAILY_LIMIT_USD", "0.30"))

    if token_db.exists():
        conn = sqlite3.connect(str(token_db))
        rows = conn.execute(
            "SELECT call_type, COUNT(*), SUM(input_tokens), SUM(output_tokens) "
            "FROM token_usage WHERE user_id=? AND created_at>=? GROUP BY call_type",
            (uid, cutoff),
        ).fetchall()
        conn.close()
        total = sum(_cost(ct, inp or 0, out or 0) for ct, _, inp, out in rows)
        total_calls = sum(c for _, c, _, _ in rows)
        print(f"  24h 額度: ${total:.4f} / ${pro_limit:.2f} ({total / pro_limit * 100:.1f}%)")
        print(f"  24h 呼叫: {total_calls} 次")
    else:
        print("  (token_usage.db 不存在)")

    # 卡片
    cards_db = udir / "cards.db"
    if cards_db.exists():
        conn = sqlite3.connect(str(cards_db))
        row = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN is_deleted=0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN is_deleted=1 THEN 1 ELSE 0 END) FROM card"
        ).fetchone()
        conn.close()
        print(f"  卡片: {row[1]} active / {row[2]} deleted / {row[0]} total")
    else:
        print("  (cards.db 不存在)")

    # 圖譜
    graph_path = udir / "graph_default.json"
    if graph_path.exists():
        links = json.loads(graph_path.read_text())
        print(f"  連結: {len(links)}")
    else:
        print("  (graph_default.json 不存在)")


# ── Level 2: 額度消耗分析 ────────────────────────────────────

def level_2(uid: str, udir: Path) -> None:
    _section("Level 2: 額度消耗分析 (72h)")

    token_db = DATA_DIR / "token_usage.db"
    if not token_db.exists():
        print("  (token_usage.db 不存在)")
        return

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    conn = sqlite3.connect(str(token_db))

    rows = conn.execute(
        "SELECT call_type, COUNT(*), SUM(input_tokens), SUM(output_tokens), "
        "AVG(input_tokens), AVG(output_tokens) "
        "FROM token_usage WHERE user_id=? AND created_at>=? "
        "GROUP BY call_type ORDER BY SUM(input_tokens) DESC",
        (uid, cutoff),
    ).fetchall()

    if not rows:
        print("  (72h 內無紀錄)")
        conn.close()
        return

    total_cost = 0
    judge_calls = 0
    print(f"\n  {'type':<22} {'calls':>6} {'avg_in':>8} {'avg_out':>8} {'cost':>10}")
    print(f"  {'-'*22} {'-'*6} {'-'*8} {'-'*8} {'-'*10}")
    for ct, calls, inp, out, avg_i, avg_o in rows:
        inp = inp or 0
        out = out or 0
        cost = _cost(ct, inp, out)
        total_cost += cost
        if ct == "judge":
            judge_calls = calls
        print(f"  {ct:<22} {calls:>6} {avg_i:>8.0f} {avg_o:>8.0f} ${cost:>9.4f}")
    print(f"  {'TOTAL':<22} {'':>6} {'':>8} {'':>8} ${total_cost:>9.4f}")

    if judge_calls and total_cost:
        judge_cost = sum(_cost(ct, inp or 0, out or 0) for ct, _, inp, out in rows if ct == "judge")
        print(f"\n  Judge 佔比: {judge_cost / total_cost * 100:.0f}%", end="")
        if judge_cost / total_cost > 0.5:
            print(" ⚠ (>50%，門檻可能太低)")
        else:
            print(" ✓")

    # 拒絕率估算
    graph_path = udir / "graph_default.json"
    if graph_path.exists() and judge_calls:
        links = json.loads(graph_path.read_text())
        recent_links = len([l for l in links if l.get("created_at", "") >= cutoff[:10]])
        rejection = (judge_calls - recent_links) / judge_calls * 100
        print(f"  拒絕率: {rejection:.0f}% ({judge_calls} judge → {recent_links} links)", end="")
        if rejection > 60:
            print(" ⚠ (>60%)")
        elif rejection < 20:
            print(" ⚠ (<20%，門檻可能太高)")
        else:
            print(" ✓")

    conn.close()


# ── Level 3: 圖譜拓撲 ───────────────────────────────────────

def _load_graph_and_cards(udir: Path):
    graph_path = udir / "graph_default.json"
    cards_db = udir / "cards.db"
    links = json.loads(graph_path.read_text()) if graph_path.exists() else []
    cards = {}
    if cards_db.exists():
        conn = sqlite3.connect(str(cards_db))
        conn.row_factory = sqlite3.Row
        cards = {
            r["id"]: dict(r)
            for r in conn.execute("SELECT id, content, meaning, is_deleted FROM card WHERE is_deleted=0")
        }
        conn.close()
    return links, cards


def level_3(uid: str, udir: Path) -> dict:
    _section("Level 3: 圖譜拓撲")

    links, cards = _load_graph_and_cards(udir)
    if not links:
        print("  (無連結)")
        return {}

    # Adjacency
    adj = defaultdict(set)
    for l in links:
        f, t = l["from_id"], l["to_id"]
        if f in cards and t in cards:
            adj[f].add(t)
            adj[t].add(f)

    degrees = {cid: len(nb) for cid, nb in adj.items()}
    isolated = [cid for cid in cards if cid not in adj]
    n_nodes = len(cards)
    n_linked = len(adj)
    n_edges = len(links)

    print(f"  節點: {n_nodes} (有連結: {n_linked}, 孤立: {len(isolated)} = {len(isolated)/n_nodes*100:.0f}%)")
    print(f"  邊數: {n_edges}")
    if n_linked > 1:
        density = 2 * n_edges / (n_linked * (n_linked - 1)) * 100
        print(f"  密度: {density:.3f}%")

    # Degree distribution
    if degrees:
        vals = list(degrees.values())
        import statistics
        print(f"  度數: min={min(vals)} max={max(vals)} mean={statistics.mean(vals):.1f} median={statistics.median(vals):.0f}")
        deg_hist = Counter(vals)
        print(f"  度數分布:")
        for d in sorted(deg_hist):
            print(f"    {d:>3}: {deg_hist[d]:>3} {_bar(deg_hist[d])}")

    # Connected components
    visited = set()
    components = []
    for node in adj:
        if node in visited:
            continue
        comp = set()
        stack = [node]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            comp.add(n)
            stack.extend(adj[n] - visited)
        components.append(comp)
    components.sort(key=len, reverse=True)

    print(f"\n  連通分量: {len(components)}")
    if components:
        print(f"  最大分量: {len(components[0])} 節點 ({len(components[0])/n_linked*100:.0f}%)")
        if len(components) > 1:
            sizes = [len(c) for c in components[:10]]
            print(f"  前 10 分量: {sizes}")

    # Clustering coefficient
    cc_list = []
    for node, neighbors in adj.items():
        k = len(neighbors)
        if k < 2:
            cc_list.append(0.0)
            continue
        triangles = 0
        nb = list(neighbors)
        for i in range(k):
            for j in range(i + 1, k):
                if nb[j] in adj.get(nb[i], set()):
                    triangles += 1
        cc_list.append(triangles / (k * (k - 1) / 2))
    avg_cc = sum(cc_list) / len(cc_list) if cc_list else 0
    random_cc = 2 * n_edges / (n_linked * (n_linked - 1)) if n_linked > 1 else 0

    print(f"\n  聚類係數: {avg_cc:.3f} (隨機圖: {random_cc:.4f}, 倍數: {avg_cc/random_cc:.0f}x)" if random_cc else f"\n  聚類係數: {avg_cc:.3f}")

    # Top hubs
    top = sorted(degrees.items(), key=lambda x: -x[1])[:5]
    print(f"\n  Top 5 hubs:")
    for cid, deg in top:
        name = cards.get(cid, {}).get("content", "?")
        print(f"    {name:<20} degree={deg}")

    return {"adj": adj, "links": links, "cards": cards, "degrees": degrees}


# ── Level 4: 連結品質 ───────────────────────────────────────

def level_4(uid: str, udir: Path) -> None:
    _section("Level 4: 連結品質")

    links, cards = _load_graph_and_cards(udir)
    if not links:
        print("  (無連結)")
        return

    # Confidence
    confs = [l["confidence"] for l in links]
    import statistics
    print(f"  Confidence: mean={statistics.mean(confs):.2f} std={statistics.stdev(confs):.2f} min={min(confs):.2f} max={max(confs):.2f}")

    # Kind distribution
    kinds = Counter(l["kind"] for l in links)
    print(f"  Kind 分布:")
    for k, c in kinds.most_common():
        pct = c / len(links) * 100
        print(f"    {k:<20} {c:>4} ({pct:.0f}%)")

    # Confidence by kind
    for kind in kinds:
        kc = [l["confidence"] for l in links if l["kind"] == kind]
        print(f"    {kind} confidence: mean={statistics.mean(kc):.2f}")

    # Recent link creation velocity
    dates = Counter(l["created_at"][:10] for l in links)
    recent = sorted(dates.items())[-7:]
    if recent:
        print(f"\n  近 7 天連結建立:")
        for d, c in recent:
            print(f"    {d}: {c:>3} {_bar(c)}")


# ── Level 5: 嵌入分析 + 閾值掃描 ────────────────────────────

def level_5(uid: str, udir: Path) -> None:
    _section("Level 5: 嵌入分析 + 閾值掃描")

    emb_path = udir / "embeddings_default.npy"
    ids_path = udir / "card_ids_default.json"
    cards_db = udir / "cards.db"

    if not emb_path.exists() or not ids_path.exists():
        print("  (embeddings 不存在)")
        return

    try:
        import numpy as np
    except ImportError:
        print("  (numpy 不可用)")
        return

    embeddings = np.load(str(emb_path))
    card_ids = json.loads(ids_path.read_text())
    n = len(card_ids)

    # Active cards count
    n_active = 0
    if cards_db.exists():
        conn = sqlite3.connect(str(cards_db))
        n_active = conn.execute("SELECT COUNT(*) FROM card WHERE is_deleted=0").fetchone()[0]
        conn.close()

    print(f"  嵌入: {n} vectors, dim={embeddings.shape[1]}")
    print(f"  覆蓋: {n}/{n_active} active cards ({n/n_active*100:.0f}%)" if n_active else f"  覆蓋: {n} vectors")

    # Cosine similarity matrix
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normed = embeddings / (norms + 1e-9)
    sim_matrix = normed @ normed.T
    upper = sim_matrix[np.triu_indices(n, k=1)]

    print(f"\n  全局相似度: mean={upper.mean():.4f} std={upper.std():.4f} min={upper.min():.4f} max={upper.max():.4f}")

    # Percentiles
    print(f"  百分位:")
    for p in [50, 75, 90, 95, 99]:
        v = np.percentile(upper, p)
        print(f"    P{p}: {v:.4f}")

    # Threshold sweep
    print(f"\n  {'閾值':>6}  {'候選對':>8}  {'每卡平均':>8}  {'佔比':>8}")
    print(f"  {'-'*6}  {'-'*8}  {'-'*8}  {'-'*8}")
    for t in [0.70, 0.75, 0.78, 0.80, 0.82, 0.85, 0.90]:
        count = int((upper > t).sum())
        avg = 2 * count / n
        pct = count / len(upper) * 100
        marker = " ◄" if abs(t - 0.78) < 0.005 else ""
        print(f"  {t:>6.2f}  {count:>8}  {avg:>8.1f}  {pct:>7.3f}%{marker}")


# ── Level 6: 異常偵測 ───────────────────────────────────────

def level_6(uid: str, udir: Path) -> None:
    _section("Level 6: 異常偵測")

    links, cards = _load_graph_and_cards(udir)
    issues = []

    # 1. 連結指向已刪除卡片
    cards_db_path = udir / "cards.db"
    if cards_db_path.exists() and links:
        conn = sqlite3.connect(str(cards_db_path))
        conn.row_factory = sqlite3.Row
        all_card_ids = {r["id"]: r for r in conn.execute("SELECT id, content, is_deleted FROM card")}
        conn.close()

        deleted_links = []
        missing_links = []
        for l in links:
            for side, cid in [("from", l["from_id"]), ("to", l["to_id"])]:
                if cid not in all_card_ids:
                    missing_links.append(f"    {l['id'][:12]}: {side}_id={cid[:12]} 不存在於 DB")
                elif all_card_ids[cid]["is_deleted"]:
                    name = all_card_ids[cid]["content"]
                    deleted_links.append(f"    {l['id'][:12]}: {side} '{name}' 已刪除但連結仍 active")

        if missing_links:
            issues.append(f"  ⚠ {len(missing_links)} 條連結指向不存在的卡片")
            issues.extend(missing_links[:5])
        if deleted_links:
            issues.append(f"  ⚠ {len(deleted_links)} 條連結指向已刪除卡片")
            issues.extend(deleted_links[:5])

    # 2. 重複連結
    if links:
        seen = set()
        dupes = 0
        for l in links:
            pair = tuple(sorted([l["from_id"], l["to_id"]]))
            if pair in seen:
                dupes += 1
            seen.add(pair)
        if dupes:
            issues.append(f"  ⚠ {dupes} 條重複連結（A↔B 有兩條）")

    # 3. 自連結
    if links:
        self_links = [l for l in links if l["from_id"] == l["to_id"]]
        if self_links:
            issues.append(f"  ⚠ {len(self_links)} 條自連結")

    # 4. 缺 embedding
    emb_ids_path = udir / "card_ids_default.json"
    if emb_ids_path.exists() and cards:
        emb_ids = set(json.loads(emb_ids_path.read_text()))
        active_ids = set(cards.keys())
        missing = active_ids - emb_ids
        if missing:
            issues.append(f"  ⚠ {len(missing)} 張 active 卡片缺 embedding")

    # 5. 已刪除卡片仍有 embedding
    if emb_ids_path.exists() and cards_db_path.exists():
        emb_ids = set(json.loads(emb_ids_path.read_text()))
        active_ids = set(cards.keys())
        stale = emb_ids - active_ids
        if stale:
            issues.append(f"  ⚠ {len(stale)} 張已刪除卡片仍佔 embedding")

    # 6. 待處理候選
    cand_path = udir / "candidates_default.json"
    if cand_path.exists():
        cands = json.loads(cand_path.read_text())
        if cands:
            issues.append(f"  ℹ {len(cands)} 個待處理候選（需跑 pipeline）")

    if issues:
        for i in issues:
            print(i)
    else:
        print("  ✓ 未發現異常")


# ── Main ─────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="KG 用戶資料與知識圖譜深度分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Levels: 1=健檢 2=額度 3=拓撲 4=連結 5=嵌入 6=異常 all=全部",
    )
    parser.add_argument("uid", help="用戶 ID（支援部分匹配）")
    parser.add_argument("level", nargs="?", default="all", help="分析層級 (1-6 或 all)")
    args = parser.parse_args()

    uid = _resolve_uid(args.uid)
    udir = DATA_DIR / "users" / uid
    if not udir.exists():
        print(f"Error: user dir not found: {udir}", file=sys.stderr)
        sys.exit(1)

    print(f"User: {uid}")

    levels = args.level
    run_all = levels == "all"

    if run_all or "1" in levels:
        level_1(uid, udir)
    if run_all or "2" in levels:
        level_2(uid, udir)
    if run_all or "3" in levels:
        level_3(uid, udir)
    if run_all or "4" in levels:
        level_4(uid, udir)
    if run_all or "5" in levels:
        level_5(uid, udir)
    if run_all or "6" in levels:
        level_6(uid, udir)

    print()


if __name__ == "__main__":
    main()
