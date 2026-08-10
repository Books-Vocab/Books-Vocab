from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ops_edit_shared import EditContext, EditError
from .ops_edit_support import (
    _CARD_UPDATABLE_FIELDS,
    _VALID_REVIEW_STATES,
    _as_utc,
    _card_brief,
    _card_store,
    _graph_store,
    _notebook_store,
    _resolve_card_id,
    _resolve_notebook_id,
    _review_fields,
    _split_multi,
)
from kg.ops_shared import data_dir

logger = logging.getLogger(__name__)


def cmd_card_add(args: argparse.Namespace) -> int:
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    nb = _resolve_notebook_id(ctx.user_dir, args.notebook)
    plan = {
        "content": args.content, "meaning": args.meaning, "pos": args.pos,
        "notebook_id": nb, "mode": args.mode,
        "examples": args.example or [], "collocations": args.collocation or [],
        "review": args.review,
    }

    def apply_fn() -> dict[str, Any]:
        store = _card_store(ctx.user_dir)
        card = store.add(
            content=args.content, meaning=args.meaning, pos=args.pos,
            examples=args.example or [], collocations=args.collocation or [],
            mode=args.mode, notebook_id=nb,
        )
        updates: dict[str, Any] = {}
        if args.note is not None:
            updates["note"] = args.note
        if args.difficulty is not None:
            updates["difficulty"] = args.difficulty
        if args.review:
            updates.update(_review_fields(args.review, args.interval, datetime.now(tz=UTC)))
        if updates:
            card = store.update(card.id, **updates) or card
        return {"card": _card_brief(card)}

    def verify_fn() -> dict[str, Any]:
        store = _card_store(ctx.user_dir)
        found = store.find_by_content(args.content, notebook_id=nb)
        return {"ok": found is not None and not found.is_deleted}

    return ctx.run(action="card-add", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)


def cmd_card_update(args: argparse.Namespace) -> int:
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    # --set field=value(可重複);value 走 JSON 解析(數字/字串/陣列皆可)。
    updates: dict[str, Any] = {}
    for pair in args.set or []:
        if "=" not in pair:
            raise EditError(f"--set 需 field=value 形式:{pair!r}")
        field, _, raw = pair.partition("=")
        field = field.strip()
        if field not in _CARD_UPDATABLE_FIELDS:
            raise EditError(
                f"欄位不可改:{field!r}。可寫欄位={sorted(_CARD_UPDATABLE_FIELDS)};"
                "複習態用 card-set-review、刪除用 card-delete"
            )
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Failed to parse --set value as JSON for user command (field=%s, raw=%r), treating as string", field, raw)
            value = raw  # 裸字串
        updates[field] = value
    if not updates:
        raise EditError("card-update 需至少一個 --set field=value")

    plan = {"card_ref": args.card, "updates": updates}
    state: dict[str, Any] = {}

    def apply_fn() -> dict[str, Any]:
        store = _card_store(ctx.user_dir)
        card = _resolve_card_id(store, args.card)
        # content 改值前驗同 notebook 衝突:unique index 是 (content, notebook_id),
        # 跨 notebook 重複不觸發 IntegrityError,但會讓 content-based 解析
        # (_resolve_card_id / find_by_content)變非確定性(dogfood A HIGH-3)。同本內
        # 已有同名卡即擋,避免悄悄造出無法被 content 唯一定位的卡。
        new_content = updates.get("content")
        if isinstance(new_content, str):
            clash = store.find_by_content(new_content, notebook_id=card.notebook_id)
            if clash is not None and clash.id != card.id:
                raise EditError(
                    f"content 衝突:notebook {card.notebook_id} 內已有 "
                    f"content={new_content!r} 的卡 {clash.id};content 須在本內唯一"
                )
        updated = store.update(card.id, **updates)
        if updated is None:
            raise EditError(f"update 失敗(卡可能已刪除):{card.id}")
        state["card_id"] = updated.id
        return {"card": _card_brief(updated)}

    def verify_fn() -> dict[str, Any]:
        store = _card_store(ctx.user_dir)
        c = store.get(state["card_id"])
        if c is None or c.is_deleted:
            return {"ok": False, "reason": "card missing/deleted"}
        mismatched = [k for k, v in updates.items() if getattr(c, k, None) != v]
        return {"ok": not mismatched, "mismatched_fields": mismatched}

    return ctx.run(action="card-update", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)


def cmd_card_set_review(args: argparse.Namespace) -> int:
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    if args.state not in _VALID_REVIEW_STATES:
        raise EditError(f"--state 須為 {_VALID_REVIEW_STATES}")
    plan = {"card_ref": args.card, "state": args.state, "interval": args.interval}
    state: dict[str, Any] = {}

    def apply_fn() -> dict[str, Any]:
        store = _card_store(ctx.user_dir)
        card = _resolve_card_id(store, args.card)
        fields = _review_fields(args.state, args.interval, datetime.now(tz=UTC))
        updated = store.update(card.id, **fields) or card
        state["card_id"] = updated.id
        state["expect_rc"] = fields["review_count"]
        state["expect_fb"] = fields["last_review_feedback"]
        return {"card": _card_brief(updated)}

    def verify_fn() -> dict[str, Any]:
        # 不只驗 review_count(`new` 的 rc=0 與初始卡無區分度,update 沒跑也 pass)——
        # 改驗 review_count + feedback + next_review_at 的**時間不變量**(TodayReview
        # 撈取依據):new→next 為空、due→next 在過去、reviewed→next 在未來。方向性
        # 檢查避開 aware/naive datetime 等值比對陷阱(dogfood C5 / A MED-5)。
        store = _card_store(ctx.user_dir)
        c = store.get(state["card_id"])
        if c is None or c.is_deleted:
            return {"ok": False, "reason": "card missing/deleted"}
        now = datetime.now(tz=UTC)
        nxt = c.next_review_at
        if args.state == "new":
            time_ok = nxt is None
        elif args.state == "due":
            time_ok = nxt is not None and _as_utc(nxt) < now
        else:  # reviewed
            time_ok = nxt is not None and _as_utc(nxt) > now
        ok = (c.review_count == state["expect_rc"]
              and c.last_review_feedback == state["expect_fb"]
              and time_ok)
        return {"ok": ok, "review_count": c.review_count,
                "next_review_at": str(nxt), "time_invariant_ok": time_ok}

    return ctx.run(action="card-set-review", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)


def cmd_card_delete(args: argparse.Namespace) -> int:
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    plan = {"card_ref": args.card, "kind": "soft-delete"}
    state: dict[str, Any] = {}

    def apply_fn() -> dict[str, Any]:
        store = _card_store(ctx.user_dir)
        card = _resolve_card_id(store, args.card)
        ok = store.delete(card.id)
        state["card_id"] = card.id
        return {"deleted": ok, "card_id": card.id}

    def verify_fn() -> dict[str, Any]:
        store = _card_store(ctx.user_dir)
        c = store.get(state["card_id"])
        return {"ok": c is None or c.is_deleted}

    return ctx.run(action="card-delete", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)


def cmd_card_import(args: argparse.Namespace) -> int:
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise EditError(f"CSV not found: {csv_path}")
    nb_id = _resolve_notebook_id(ctx.user_dir, args.notebook)
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # header 正規化成小寫:CSV 用 `Content`/`CONTENT` 不該靜默跳過全批。
        fieldnames = [h.strip().lower() for h in (reader.fieldnames or [])]
        reader.fieldnames = fieldnames
        if "content" not in fieldnames:
            raise EditError(
                f"CSV 缺 content 欄;偵測到 headers={fieldnames}。"
                "必要欄:content, meaning;可選:pos, examples, collocations, note, "
                "difficulty, review_state, review_interval(examples/collocations 多值用 | 分隔)"
            )
        all_rows = list(reader)
    rows = [r for r in all_rows if (r.get("content") or "").strip()]
    blank_meaning = sum(1 for r in rows if not (r.get("meaning") or "").strip())
    has_review_col = "review_state" in fieldnames
    plan = {
        "csv": str(csv_path), "notebook_id": nb_id,
        "row_count": len(rows),
        "skipped_blank_content": len(all_rows) - len(rows),
        "blank_meaning_rows": blank_meaning,  # >0 會在 commit 時被擋
        "has_review_col": has_review_col,
        "sample": [r.get("content") for r in rows[:5]],
    }

    def _prevalidate_rows() -> None:
        """任何 store.add 之前一次掃完整批 —— 失敗即 0 寫入(原子性,dogfood B2)。

        此前 `float(review_interval)` 在逐筆寫入迴圈中途才炸,已寫的卡留在 DB、
        錯誤行之後的卡沒寫,工具卻報 committed=False —— 與磁碟矛盾。把 meaning /
        review_state / review_interval 的格式驗證全部前移到寫入前。
        """
        if blank_meaning:
            raise EditError(
                f"{blank_meaning} 列 meaning 空白;demo 卡需有定義,檢查 CSV 欄位名/內容"
            )
        for i, r in enumerate(rows):
            rv = (r.get("review_state") or "").strip()
            if not rv:
                continue
            if rv not in _VALID_REVIEW_STATES:
                raise EditError(f"列 {i} review_state 非法:{rv!r}(僅 {_VALID_REVIEW_STATES})")
            raw_iv = (r.get("review_interval") or "").strip()
            if raw_iv:
                try:
                    float(raw_iv)
                except ValueError as exc:
                    raise EditError(f"列 {i} review_interval 非數值:{raw_iv!r}") from exc

    def apply_fn() -> dict[str, Any]:
        _prevalidate_rows()
        store = _card_store(ctx.user_dir)
        now = datetime.now(tz=UTC)
        # 用 pre/post id diff 算**真實**新增數 —— CardStore.add 對既有 content
        # 冪等回傳舊卡,無腦 +1 會把「跳過的重複」誤計為新增。
        pre_ids = {c.id for c in store.all(notebook_id=nb_id)}
        for r in rows:
            card = store.add(
                content=r["content"].strip(),
                meaning=(r.get("meaning") or "").strip(),
                pos=(r.get("pos") or "").strip() or None,
                examples=_split_multi(r.get("examples")),
                collocations=_split_multi(r.get("collocations")),
                notebook_id=nb_id,
            )
            rv = (r.get("review_state") or "").strip()
            if rv in _VALID_REVIEW_STATES:
                raw_iv = (r.get("review_interval") or "").strip()
                iv = float(raw_iv) if raw_iv else None
                store.update(card.id, **_review_fields(rv, iv, now))
        post_ids = {c.id for c in store.all(notebook_id=nb_id)}
        actually_new = len(post_ids - pre_ids)
        return {"rows": len(rows), "actually_new": actually_new,
                "skipped_dup": len(rows) - actually_new}

    def verify_fn() -> dict[str, Any]:
        store = _card_store(ctx.user_dir)
        missing = [r["content"] for r in rows
                   if store.find_by_content(r["content"].strip(), notebook_id=nb_id) is None]
        return {"ok": not missing, "missing_count": len(missing),
                "missing_sample": missing[:5]}

    return ctx.run(action="card-import", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)

def cmd_card_move(args: argparse.Namespace) -> int:
    """把卡移到別的筆記本 —— 修正 card-add 誤存 name 的孤兒卡(dogfood A LOW-4)。

    notebook_id 不在 card-update 白名單(刻意),故移動走此專屬語意:解析目標本、
    驗目標本內無同 content 衝突(unique index)、再改 notebook_id。

    **link 處理**:圖譜為 per-notebook、link 兩端須同本。卡搬本後,原本連著它的
    link 必然變成跨本(另一端還在原本),違反不變量 → **硬刪**那些 link(維持「無跨本
    link」不變式),result 報告刪除數,operator 可在目標本用 link-add 重建(dogfood
    D HIGH-1)。link id 連的是 card id,故掃所有 notebook graph 找涉及此卡的 link。
    """
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    target_nb = _resolve_notebook_id(ctx.user_dir, args.to_notebook)
    plan = {"card_ref": args.card, "to_notebook": target_nb}
    state: dict[str, Any] = {}

    def apply_fn() -> dict[str, Any]:
        store = _card_store(ctx.user_dir)
        card = _resolve_card_id(store, args.card)
        if card.notebook_id == target_nb:
            raise EditError(f"卡已在 notebook {target_nb},無需移動")
        clash = store.find_by_content(card.content, notebook_id=target_nb)
        if clash is not None and clash.id != card.id:
            raise EditError(
                f"目標 notebook {target_nb} 內已有 content={card.content!r} 的卡 {clash.id}"
            )
        moved_id = card.id
        # 搬本前先硬刪所有 notebook graph 中涉及此卡的 link(搬後必跨本)。掃全部本
        # (default + 所有既存)的 graph,找 from/to == moved_id 的 link 刪除。
        nb_store = _notebook_store(ctx.user_dir)
        all_nb_ids = {"default"} | {nb.id for nb in nb_store.all()}
        purged_links: list[str] = []
        for gnb in all_nb_ids:
            graph = _graph_store(ctx.user_dir, gnb)
            for lk in graph.get_links_for(moved_id):
                graph.hard_delete_link(lk.id, source="ops")
                purged_links.append(lk.id)
        updated = store.update(card.id, notebook_id=target_nb)
        if updated is None:
            raise EditError(f"move 失敗(卡可能已刪除):{card.id}")
        state["card_id"] = updated.id
        return {"card": _card_brief(updated),
                "purged_links": purged_links,
                "purged_count": len(purged_links)}

    def verify_fn() -> dict[str, Any]:
        store = _card_store(ctx.user_dir)
        c = store.get(state["card_id"])
        return {"ok": c is not None and not c.is_deleted and c.notebook_id == target_nb}

    return ctx.run(action="card-move", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)
