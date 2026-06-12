from __future__ import annotations

from .ops_edit_support import (
    Any,
    EditContext,
    EditError,
    _assert_clean_notebook_name,
    _card_store,
    _notebook_store,
    _resolve_notebook_id,
    argparse,
    data_dir,
    sys,
)


def cmd_notebook_create(args: argparse.Namespace) -> int:
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    _assert_clean_notebook_name(args.name)
    plan = {"name": args.name, "color": args.color, "cover_pattern": args.cover}
    state: dict[str, Any] = {}

    def apply_fn() -> dict[str, Any]:
        store = _notebook_store(ctx.user_dir)
        # 同名既存不擋(系統允許重名),但 warn:重名會讓 name→id 解析取最舊那本,
        # operator 易混淆(dogfood D LOW-1)。診斷走 stderr,不污染 --json stdout。
        dup = next((nb for nb in store.all() if nb.name == args.name), None)
        if dup is not None:
            print(f"⚠ 已存在同名 notebook(id={dup.id});name→id 解析將取最舊那本",
                  file=sys.stderr)
        nb = store.create(name=args.name, color=args.color, cover_pattern=args.cover)
        state["nb_id"] = nb.id
        return {"notebook": {"id": nb.id, "name": nb.name, "color": nb.color,
                             "cover_pattern": nb.cover_pattern}}

    def verify_fn() -> dict[str, Any]:
        store = _notebook_store(ctx.user_dir)
        return {"ok": store.get(state["nb_id"]) is not None}

    return ctx.run(action="notebook-create", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)

def cmd_notebook_update(args: argparse.Namespace) -> int:
    """改筆記本 name/color/cover —— 讀端有 notebook 但寫端此前無法改名(dogfood A LOW-4)。"""
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    nb_id = _resolve_notebook_id(ctx.user_dir, args.notebook)
    updates: dict[str, Any] = {}
    if args.name is not None:
        _assert_clean_notebook_name(args.name)
        updates["name"] = args.name
    if args.color is not None:
        updates["color"] = args.color
    if args.cover is not None:
        updates["cover_pattern"] = args.cover
    if args.sort_order is not None:
        updates["sort_order"] = args.sort_order
    if not updates:
        raise EditError("notebook-update 需至少一個 --name / --color / --cover / --sort-order")
    plan = {"notebook_id": nb_id, "updates": updates}

    def apply_fn() -> dict[str, Any]:
        store = _notebook_store(ctx.user_dir)
        nb = store.update(nb_id, **updates)
        if nb is None:
            raise EditError(f"notebook not found 或已刪除:{nb_id}")
        return {"notebook": {"id": nb.id, "name": nb.name, "color": nb.color,
                             "cover_pattern": nb.cover_pattern, "sort_order": nb.sort_order}}

    def verify_fn() -> dict[str, Any]:
        store = _notebook_store(ctx.user_dir)
        nb = store.get(nb_id)
        if nb is None:
            return {"ok": False, "reason": "notebook missing"}
        mism = [k for k, v in updates.items() if getattr(nb, k, None) != v]
        return {"ok": not mism, "mismatched": mism}

    return ctx.run(action="notebook-update", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)


def cmd_notebook_delete(args: argparse.Namespace) -> int:
    """軟刪筆記本(default 不可刪)—— 清掉重複 seed 留下的孤兒本(dogfood A LOW-4)。

    **孤兒卡防護**(dogfood D HIGH-2):軟刪 notebook 不會動該本的卡,卡的 notebook_id
    仍指向已刪本 → iOS `NotebookStore.all()` 不回傳已刪本,這些卡從任何 UI 路徑都查不
    到(資料在但不可訪問)。故預設**拒絕刪除非空 notebook**,列出卡數要 operator 先
    `card-move` 搬出;`--cascade` 才一併軟刪該本所有卡(走 `CardStore.soft_delete_by_notebook`)。
    """
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    nb_id = _resolve_notebook_id(ctx.user_dir, args.notebook)
    if nb_id == "default":
        raise EditError("default notebook 不可刪除")
    card_count = _card_store(ctx.user_dir).count(notebook_id=nb_id)
    if card_count > 0 and not args.cascade:
        raise EditError(
            f"notebook {nb_id} 內尚有 {card_count} 張卡;刪本會使其成孤兒卡(iOS 不可見)。"
            "先用 card-move 搬出,或加 --cascade 一併軟刪這些卡"
        )
    plan = {"notebook_id": nb_id, "kind": "soft-delete",
            "card_count": card_count, "cascade": args.cascade}

    def apply_fn() -> dict[str, Any]:
        cards_deleted = 0
        if args.cascade and card_count > 0:
            cards_deleted = _card_store(ctx.user_dir).soft_delete_by_notebook(nb_id)
        store = _notebook_store(ctx.user_dir)
        result = store.delete(nb_id)  # True=刪 / None=已刪(冪等) / False=not found 或 default
        if result is False:
            raise EditError(f"notebook 刪除失敗(not found 或為 default):{nb_id}")
        return {"deleted": nb_id, "already_deleted": result is None,
                "cards_soft_deleted": cards_deleted}

    def verify_fn() -> dict[str, Any]:
        store = _notebook_store(ctx.user_dir)
        # 本已刪 + (cascade 時)該本無殘留 active 卡 → 無孤兒。
        active_left = _card_store(ctx.user_dir).count(notebook_id=nb_id)
        return {"ok": not store.exists(nb_id) and (not args.cascade or active_left == 0),
                "active_cards_left": active_left}

    return ctx.run(action="notebook-delete", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)
