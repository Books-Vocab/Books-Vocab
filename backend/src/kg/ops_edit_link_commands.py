from __future__ import annotations

import argparse
from typing import Any

from .ops_edit_shared import EditContext, EditError, assert_safe_uid, emit, user_dir_for
from .ops_edit_support import (
    _card_store,
    _graph_store,
    _link_on_disk,
    _resolve_card_in_notebook,
    _resolve_notebook_id,
)
from kg.graph.models import LinkKind
from kg.ops_shared import data_dir


def cmd_link_add(args: argparse.Namespace) -> int:
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    if args.kind not in (LinkKind.CONTRASTS_WITH, LinkKind.SHARES_USAGE):
        raise EditError(f"--kind 須為 contrasts_with | shares_usage,得到 {args.kind!r}")
    if not 0.0 <= args.confidence <= 1.0:
        raise EditError("--confidence 須在 0.0 ~ 1.0")
    nb_id = _resolve_notebook_id(ctx.user_dir, args.notebook)
    plan = {"from": args.from_ref, "to": args.to_ref, "kind": args.kind,
            "confidence": args.confidence, "reason": args.reason, "notebook_id": nb_id}
    state: dict[str, Any] = {}

    def apply_fn() -> dict[str, Any]:
        cards = _card_store(ctx.user_dir)
        # link 嚴格同本(圖譜 per-notebook):兩端 card 必須在 nb_id 內。卡在別本時給
        # 精準錯誤(指出在哪本),而非籠統 card not found(dogfood D MED-3 / E F4)。
        from_card = _resolve_card_in_notebook(cards, args.from_ref, nb_id)
        to_card = _resolve_card_in_notebook(cards, args.to_ref, nb_id)
        graph = _graph_store(ctx.user_dir, nb_id)
        # add_link 對既有 pair 冪等回傳舊 link(不更新 confidence/kind/reason)。先探
        # 既有,讓 result 顯式標 idempotent,operator 才不會誤以為改值生效(dogfood C8;
        # 要改既有用 link-update)。
        pre_existing = graph.find_link_between(from_card.id, to_card.id)
        if pre_existing is not None and args.if_exists == "update":
            link = graph.update_link(
                pre_existing.id,
                source="ops",
                kind=LinkKind(args.kind),
                confidence=args.confidence,
                reason=args.reason,
            )
        else:
            link = graph.add_link(
                from_id=from_card.id, to_id=to_card.id,
                kind=LinkKind(args.kind), confidence=args.confidence, reason=args.reason,
                source="ops",
            )
        state["link_id"] = link.id
        is_idem = pre_existing is not None and pre_existing.id == link.id
        semantic = "updated-existing" if pre_existing is not None and args.if_exists == "update" else "kept-existing"
        return {"link": {"id": link.id, "from": from_card.content, "to": to_card.content,
                         "kind": str(link.kind), "confidence": link.confidence, "reason": link.reason},
                "idempotent": is_idem,
                "if_exists": args.if_exists,
                "existing_semantics": semantic if pre_existing is not None else "created-new"}

    def verify_fn() -> dict[str, Any]:
        # 讀**磁碟** JSON 驗證這條 link 落盤,而非讀快取實例的記憶體(dogfood C1)。
        graph = _graph_store(ctx.user_dir, nb_id)
        lid = state.get("link_id")
        return {"ok": lid is not None and _link_on_disk(graph, lid),
                "link_count": graph.link_count()}

    return ctx.run(action="link-add", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)


def cmd_link_delete(args: argparse.Namespace) -> int:
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    nb_id = _resolve_notebook_id(ctx.user_dir, args.notebook)
    plan = {"link_id": args.link_id, "notebook_id": nb_id}

    def apply_fn() -> dict[str, Any]:
        graph = _graph_store(ctx.user_dir, nb_id)
        if graph.get_link(args.link_id) is None:
            raise EditError(f"link not found: {args.link_id}")
        from_id, to_id = graph.hard_delete_link(args.link_id, source="ops")
        return {"deleted_link": args.link_id, "from_id": from_id, "to_id": to_id}

    def verify_fn() -> dict[str, Any]:
        # 讀磁碟確認 link 已從盤上移除(繞快取記憶體,dogfood C1)。
        graph = _graph_store(ctx.user_dir, nb_id)
        return {"ok": not _link_on_disk(graph, args.link_id)}

    return ctx.run(action="link-delete", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)

def cmd_link_list(args: argparse.Namespace) -> int:
    """列出某 notebook 的 active 連結(含 link id + 兩端 card content)。唯讀。

    讓 link-update / link-delete 不必手 cat graph JSON 查 link id(dogfood E F3)。
    與 list-backups 同性質 —— 輔助寫操作的唯讀查詢,不走 EditContext。
    """
    dd = data_dir()
    assert_safe_uid(args.uid)
    user_dir = user_dir_for(dd, args.uid)
    if not user_dir.exists():
        raise EditError(f"user not found: {args.uid}")
    nb_id = _resolve_notebook_id(user_dir, args.notebook)
    cards = _card_store(user_dir)
    graph = _graph_store(user_dir, nb_id)
    links = []
    for lk in graph.all_links():
        if lk.status != "active":
            continue
        fc = cards.get(lk.from_id)
        tc = cards.get(lk.to_id)
        links.append({
            "id": lk.id,
            "from": fc.content if fc else lk.from_id,
            "to": tc.content if tc else lk.to_id,
            "kind": str(lk.kind), "confidence": lk.confidence, "reason": lk.reason,
        })
    emit({"action": "link-list", "uid": args.uid, "notebook_id": nb_id,
          "count": len(links), "links": links}, json_mode=args.json)
    return 0

def cmd_link_update(args: argparse.Namespace) -> int:
    """改連結 confidence/reason/kind —— 此前只能 delete+add(dogfood C8 / A LOW-4)。"""
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    nb_id = _resolve_notebook_id(ctx.user_dir, args.notebook)
    updates: dict[str, Any] = {}
    if args.confidence is not None:
        if not 0.0 <= args.confidence <= 1.0:
            raise EditError("--confidence 須在 0.0 ~ 1.0")
        updates["confidence"] = args.confidence
    if args.reason is not None:
        updates["reason"] = args.reason
    if args.kind is not None:
        if args.kind not in (LinkKind.CONTRASTS_WITH, LinkKind.SHARES_USAGE):
            raise EditError(f"--kind 須為 contrasts_with | shares_usage,得到 {args.kind!r}")
        updates["kind"] = LinkKind(args.kind)
    if not updates:
        raise EditError("link-update 需至少一個 --confidence / --reason / --kind")
    plan = {"link_id": args.link_id, "notebook_id": nb_id,
            "updates": {k: str(v) for k, v in updates.items()}}

    def apply_fn() -> dict[str, Any]:
        graph = _graph_store(ctx.user_dir, nb_id)
        if graph.get_link(args.link_id) is None:
            raise EditError(f"link not found: {args.link_id}")
        lk = graph.update_link(args.link_id, source="ops", **updates)
        return {"link": {"id": lk.id, "confidence": lk.confidence,
                         "reason": lk.reason, "kind": str(lk.kind)}}

    def verify_fn() -> dict[str, Any]:
        # 讀盤確認 link 仍在(C1);值用記憶體實例比對(update_link 已 flush 落盤)。
        graph = _graph_store(ctx.user_dir, nb_id)
        lk = graph.get_link(args.link_id)
        if lk is None or not _link_on_disk(graph, args.link_id):
            return {"ok": False, "reason": "link missing on disk"}
        mism = [k for k, v in updates.items() if getattr(lk, k, None) != v]
        return {"ok": not mism, "mismatched": [str(m) for m in mism]}

    return ctx.run(action="link-update", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)
