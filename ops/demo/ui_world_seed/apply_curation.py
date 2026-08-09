#!/usr/bin/env python3
"""UI World seed 策展：curation plan + seed spec → 新 seed spec（確定式）。

輸入輸出都是 `kg.seed_spec.v1`（見 docs/reference/ops_state_plane.md §1.1）；
plan 是 `kg.curation_plan.v1`（remove + assign，由策展編輯產出）。轉換全程無
時鐘/隨機依賴，同 input 重跑 byte 相等。

**只做結構策展**（剔字 / 分本 / notebook 重建 / link 收斂）。review 時間欄位
一律不動——複習歷史敘事的唯一 owner 是同目錄 `shape_history.py`（原
`_rebalance_reviews` 過期山攤平已退役、由它收編）。pipeline：
`ops_cli world-export` → `apply_curation.py`（結構）→ `shape_history.py`
（敘事）→ `build_demo.py emit-ios --spec`。

不變量（違反即 CurationError fail-loud，絕不靜默丟卡）：
- remove ∪ assign 恰好覆蓋 spec 全卡；assign 目標必在 notebook_meta。
- link 兩端卡必須落在同一 notebook（link 嚴格 per-notebook），否則列名報錯。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PLAN_SCHEMA = "kg.curation_plan.v1"
SPEC_SCHEMA = "kg.seed_spec.v1"


class CurationError(Exception):
    pass


def apply(spec: dict[str, Any], plan: dict[str, Any], *,
          notebook_meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if spec.get("schema") != SPEC_SCHEMA:
        raise CurationError(f"spec schema 不是 {SPEC_SCHEMA}: {spec.get('schema')!r}")
    if plan.get("schema") != PLAN_SCHEMA:
        raise CurationError(f"plan schema 不是 {PLAN_SCHEMA}: {plan.get('schema')!r}")

    remove = {r["word"] for r in plan.get("remove", [])}
    assign: dict[str, str] = dict(plan.get("assign", {}))
    all_words = {c["content"] for c in spec["cards"]}

    covered = remove | set(assign)
    missing = sorted(all_words - covered)
    if missing:
        raise CurationError(f"plan 未覆蓋 {len(missing)} 卡: {missing[:10]}")
    overlap = sorted(remove & set(assign))
    if overlap:
        raise CurationError(f"remove 與 assign 重疊: {overlap[:10]}")
    unknown = sorted(set(assign) - all_words) + sorted(remove - all_words)
    if unknown:
        raise CurationError(f"plan 含 spec 沒有的字: {unknown[:10]}")
    bad_targets = sorted({nb for nb in assign.values() if nb not in notebook_meta})
    if bad_targets:
        raise CurationError(f"assign 目標不在 notebook_meta: {bad_targets}")

    defaults = [name for name, m in notebook_meta.items() if m.get("is_default")]
    if len(defaults) != 1:
        raise CurationError(f"notebook_meta 必須恰好一本 is_default，現為 {defaults}")

    notebooks = [
        {"name": name, "color": meta.get("color"),
         "cover_pattern": meta.get("cover_pattern"), "sort_order": i,
         "is_default": bool(meta.get("is_default", False))}
        for i, (name, meta) in enumerate(notebook_meta.items())
    ]

    cards = [json.loads(json.dumps(c, ensure_ascii=False))
             for c in spec["cards"] if c["content"] not in remove]
    for card in cards:
        card["notebook"] = assign[card["content"]]

    nb_of = {c["content"]: c["notebook"] for c in cards}
    links: list[dict[str, Any]] = []
    broken: list[str] = []
    for link in spec.get("links", []):
        if link["from"] in remove or link["to"] in remove:
            continue  # 端點被剔除 ⇒ link 隨之剔除（刻意，不算 broken）
        a, b = nb_of[link["from"]], nb_of[link["to"]]
        if a != b:
            broken.append(f"{link['from']}({a}) ↔ {link['to']}({b})")
            continue
        new_link = dict(link)
        new_link["notebook"] = a
        links.append(new_link)
    if broken:
        raise CurationError(
            f"{len(broken)} 條 link 端點被拆到不同本（同分量必須同本）: {broken[:10]}")

    cards.sort(key=lambda c: (c["notebook"], c["content"]))
    links.sort(key=lambda l: (l["notebook"], l["from"], l["to"], l["kind"]))
    out = dict(spec)
    out["notebooks"] = notebooks
    out["cards"] = cards
    out["links"] = links
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spec", help="輸入 kg.seed_spec.v1 JSON")
    ap.add_argument("plan", help="kg.curation_plan.v1 JSON")
    ap.add_argument("meta", help="notebook_meta JSON（name → {color,cover_pattern,is_default}）")
    ap.add_argument("--out", help="輸出路徑（預設 stdout）")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    result = apply(spec, plan, notebook_meta=meta)
    payload = json.dumps(result, ensure_ascii=False, indent=1) + "\n"
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"apply_curation: {args.out} (notebooks={len(result['notebooks'])} "
              f"cards={len(result['cards'])} links={len(result['links'])})")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
