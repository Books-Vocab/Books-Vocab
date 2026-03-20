#!/usr/bin/env python3
"""Graph pipeline analysis — threshold vs connection count + actual link audit.

Usage:
    python ops/graph_analysis.py              # full analysis for user chen
    python ops/graph_analysis.py -u <user>    # specify user
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "backend" / "data" / "users"


def load_data(user: str):
    """Load embeddings, card IDs, graph, candidates, and card DB."""
    udir = DATA / user

    # Embeddings
    emb_path = udir / "embeddings.npy"
    ids_path = udir / "card_ids.json"
    if not emb_path.exists() or not ids_path.exists():
        sys.exit(f"✗ Embedding files not found for user '{user}'")
    embeddings = np.load(emb_path)
    card_ids = json.loads(ids_path.read_text())

    # Graph
    graph_path = udir / "graph.json"
    links = []
    if graph_path.exists():
        data = json.loads(graph_path.read_text())
        links = data if isinstance(data, list) else data.get("links", [])

    # Candidates
    cand_path = udir / "candidates.json"
    candidates = []
    if cand_path.exists():
        candidates = json.loads(cand_path.read_text())

    # Card DB
    db_path = udir / "cards.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    return embeddings, card_ids, links, candidates, conn


def cosine_similarity_matrix(embeddings: np.ndarray) -> np.ndarray:
    """Compute full pairwise cosine similarity matrix."""
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normed = embeddings / (norms + 1e-9)
    return normed @ normed.T


def card_name(conn, card_id: str) -> str:
    row = conn.execute("SELECT content FROM card WHERE id=?", (card_id,)).fetchone()
    return row[0] if row else "?"


def section(title: str):
    print(f"\n{'='*70}")
    print(f" {title}")
    print(f"{'='*70}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--user", default="chen")
    args = parser.parse_args()

    embeddings, card_ids, links, candidates, conn = load_data(args.user)
    n = len(card_ids)
    sim_matrix = cosine_similarity_matrix(embeddings)

    # ── 1. 閾值 vs 候選配對數量 ─────────────────────────────────────────
    section(f"閾值 vs 候選配對數 (embedding {n} 張卡片, {n*(n-1)//2} 個配對)")

    # Extract upper triangle (exclude diagonal)
    upper_indices = np.triu_indices(n, k=1)
    all_sims = sim_matrix[upper_indices]

    print(f"\n  全局相似度統計:")
    print(f"    min  = {all_sims.min():.4f}")
    print(f"    mean = {all_sims.mean():.4f}")
    print(f"    med  = {np.median(all_sims):.4f}")
    print(f"    max  = {all_sims.max():.4f}")
    print(f"    std  = {all_sims.std():.4f}")

    # Percentiles
    percentiles = [50, 75, 90, 95, 99, 99.5, 99.9]
    print(f"\n  百分位分布:")
    for p in percentiles:
        v = np.percentile(all_sims, p)
        print(f"    P{p:5.1f} = {v:.4f}")

    # Threshold sweep
    thresholds = [0.50, 0.55, 0.60, 0.62, 0.64, 0.65, 0.655, 0.66, 0.67,
                  0.68, 0.70, 0.72, 0.75, 0.80, 0.85, 0.90]
    print(f"\n  {'閾值':>8s}  {'候選配對數':>10s}  {'佔總配對%':>10s}  {'每張卡平均連結':>14s}  {'圖示'}")
    print(f"  {'─'*8}  {'─'*10}  {'─'*10}  {'─'*14}  {'─'*30}")
    for t in thresholds:
        count = int(np.sum(all_sims > t))
        pct = 100.0 * count / len(all_sims)
        avg_per_card = 2 * count / n  # each pair contributes to 2 cards
        bar = "█" * min(int(count / 5), 50)
        marker = " ◄── 目前" if t == 0.655 else ""
        print(f"  {t:8.3f}  {count:10d}  {pct:9.3f}%  {avg_per_card:14.1f}  {bar}{marker}")

    # ── 2. Top-k 分析（pipeline 用 k=3）──────────────────────────────────
    section("Top-k 分析 (pipeline 取 k=3)")

    # For each card, get top-3 similarities
    topk_above = 0
    topk_total = 0
    topk_scores = []
    for i in range(n):
        sims_i = sim_matrix[i].copy()
        sims_i[i] = -1  # exclude self
        top3_idx = np.argsort(sims_i)[-3:][::-1]
        for j in top3_idx:
            topk_total += 1
            score = sims_i[j]
            topk_scores.append(score)
            if score > 0.655:
                topk_above += 1

    topk_scores = np.array(topk_scores)
    print(f"\n  每張卡 top-3 neighbor 相似度統計 (共 {topk_total} 個):")
    print(f"    min  = {topk_scores.min():.4f}")
    print(f"    mean = {topk_scores.mean():.4f}")
    print(f"    med  = {np.median(topk_scores):.4f}")
    print(f"    max  = {topk_scores.max():.4f}")
    print(f"    > 0.655 (通過閾值): {topk_above}/{topk_total} ({100*topk_above/topk_total:.1f}%)")

    # ── 3. 實際連結審計 ──────────────────────────────────────────────────
    section(f"實際圖譜連結審計 (共 {len(links)} 條)")

    active = [lk for lk in links if lk.get("status", "active") == "active"]
    deprecated = [lk for lk in links if lk.get("status") == "deprecated"]
    print(f"\n  active: {len(active)}, deprecated: {len(deprecated)}")

    # Kind breakdown
    kind_counts = Counter(lk["kind"] for lk in active)
    print(f"\n  類型分布:")
    for kind, cnt in kind_counts.most_common():
        print(f"    {kind:20s} {cnt:3d}")

    # Confidence breakdown
    confs = [lk["confidence"] for lk in active]
    if confs:
        confs_arr = np.array(confs)
        print(f"\n  置信度統計:")
        print(f"    min={confs_arr.min():.2f}  mean={confs_arr.mean():.2f}  "
              f"med={np.median(confs_arr):.2f}  max={confs_arr.max():.2f}")

    # Node degree distribution
    degree = Counter()
    for lk in active:
        degree[lk["from_id"]] += 1
        degree[lk["to_id"]] += 1

    total_cards_active = conn.execute("SELECT COUNT(*) FROM card WHERE is_deleted=0").fetchone()[0]
    linked_cards = len(degree)
    isolated_cards = total_cards_active - linked_cards

    print(f"\n  節點統計:")
    print(f"    有 embedding 的卡片: {n}")
    print(f"    DB 中 active 卡片: {total_cards_active}")
    print(f"    有連結的卡片: {linked_cards}")
    print(f"    孤立卡片 (無連結): {isolated_cards}")

    if degree:
        degrees = list(degree.values())
        deg_arr = np.array(degrees)
        print(f"\n  度數分布:")
        print(f"    min={deg_arr.min()}  mean={deg_arr.mean():.1f}  "
              f"med={int(np.median(deg_arr))}  max={deg_arr.max()}")
        deg_dist = Counter(degrees)
        for d in sorted(deg_dist.keys()):
            bar = "█" * deg_dist[d]
            print(f"    度={d}: {deg_dist[d]:3d} 張卡  {bar}")

    # ── 4. 問題偵測 ──────────────────────────────────────────────────────
    section("問題偵測")

    issues = []

    # 4a. 連結指向已刪除卡片
    for lk in active:
        for side, card_id in [("from", lk["from_id"]), ("to", lk["to_id"])]:
            row = conn.execute("SELECT is_deleted, content FROM card WHERE id=?", (card_id,)).fetchone()
            if row is None:
                issues.append(f"  ⚠ 連結 {lk['id']}: {side}_id={card_id} 在 DB 中不存在")
            elif row["is_deleted"]:
                issues.append(f"  ⚠ 連結 {lk['id']}: {side} '{row['content']}' 已被刪除但連結仍 active")

    # 4b. 連結的 embedding 相似度 vs 閾值
    id_to_idx = {cid: i for i, cid in enumerate(card_ids)}
    low_sim_links = []
    for lk in active:
        idx_a = id_to_idx.get(lk["from_id"])
        idx_b = id_to_idx.get(lk["to_id"])
        if idx_a is not None and idx_b is not None:
            sim = sim_matrix[idx_a, idx_b]
            if sim < 0.655:
                na = card_name(conn, lk["from_id"])
                nb = card_name(conn, lk["to_id"])
                low_sim_links.append((lk, sim, na, nb))

    if low_sim_links:
        issues.append(f"\n  ⚠ {len(low_sim_links)} 條連結的 embedding 相似度低於閾值 0.655:")
        for lk, sim, na, nb in sorted(low_sim_links, key=lambda x: x[1]):
            issues.append(f"    {na} <-> {nb}  sim={sim:.4f}  kind={lk['kind']}  conf={lk['confidence']}")

    # 4c. 缺少 embedding 的 active 卡片
    active_ids = set(
        r[0] for r in conn.execute("SELECT id FROM card WHERE is_deleted=0").fetchall()
    )
    embedded_ids = set(card_ids)
    missing_emb = active_ids - embedded_ids
    if missing_emb:
        issues.append(f"\n  ⚠ {len(missing_emb)} 張 active 卡片缺少 embedding:")
        for cid in list(missing_emb)[:10]:
            name = card_name(conn, cid)
            issues.append(f"    {cid}: {name}")
        if len(missing_emb) > 10:
            issues.append(f"    ... 還有 {len(missing_emb)-10} 張")

    # 4d. 已刪除卡片仍有 embedding
    deleted_with_emb = embedded_ids - active_ids
    if deleted_with_emb:
        issues.append(f"\n  ⚠ {len(deleted_with_emb)} 張已刪除卡片仍佔用 embedding 空間")

    # 4e. Duplicate links (A→B and B→A both exist)
    link_pairs = set()
    duplicates = []
    for lk in active:
        pair = tuple(sorted([lk["from_id"], lk["to_id"]]))
        if pair in link_pairs:
            na = card_name(conn, lk["from_id"])
            nb = card_name(conn, lk["to_id"])
            duplicates.append(f"    {na} <-> {nb} (重複連結 id={lk['id']})")
        link_pairs.add(pair)
    if duplicates:
        issues.append(f"\n  ⚠ {len(duplicates)} 條重複連結 (A↔B 有兩條):")
        issues.extend(duplicates)

    # 4f. Self-links
    self_links = [lk for lk in active if lk["from_id"] == lk["to_id"]]
    if self_links:
        issues.append(f"\n  ⚠ {len(self_links)} 條自連結:")
        for lk in self_links:
            na = card_name(conn, lk["from_id"])
            issues.append(f"    {na} (id={lk['id']})")

    # 4g. Candidates status
    if candidates:
        issues.append(f"\n  ℹ {len(candidates)} 個待處理候選配對 (需跑 pipeline step 2 judge)")

    if issues:
        for iss in issues:
            print(iss)
    else:
        print("  ✓ 未發現問題")

    # ── 5. 高相似度但無連結的配對 ────────────────────────────────────────
    section("高相似度但無連結的配對 (潛在遺漏)")

    existing_pairs = set()
    for lk in links:
        existing_pairs.add(tuple(sorted([lk["from_id"], lk["to_id"]])))

    missed = []
    for i in range(n):
        for j in range(i+1, n):
            sim = sim_matrix[i, j]
            if sim > 0.70:  # High similarity threshold for "suspicious misses"
                pair = tuple(sorted([card_ids[i], card_ids[j]]))
                if pair not in existing_pairs:
                    na = card_name(conn, card_ids[i])
                    nb = card_name(conn, card_ids[j])
                    missed.append((sim, na, nb, card_ids[i], card_ids[j]))

    missed.sort(reverse=True)
    if missed:
        print(f"\n  相似度 > 0.70 但無連結: {len(missed)} 對")
        for sim, na, nb, _, _ in missed[:20]:
            print(f"    {na} <-> {nb}  sim={sim:.4f}")
        if len(missed) > 20:
            print(f"    ... 還有 {len(missed)-20} 對")
    else:
        print("  ✓ 無遺漏")

    conn.close()
    print()


if __name__ == "__main__":
    main()
