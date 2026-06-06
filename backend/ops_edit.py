#!/usr/bin/env python3
"""ops_edit.py — container 內部署的**寫入**工具(`ops_cli.py` 唯讀面的可寫對應)。

`ops_cli.py` 唯讀查詢;本檔負責**安全地編輯** production 業務資料:建用戶 / 增改刪
單字卡 / 設複習態 / 建筆記本 / 連結知識圖譜 / 一次性 seed 整套 demo 帳號 / restore。

安全模型(全部由 `kg.ops_edit_shared.EditContext` 強制)
-----------------------------------------------------
* **dry-run 預設** —— 不加 `--commit` 只印 plan,零磁碟寫入。
* **寫前自動 tar 備份** 整個 user_dir 到 `data_dir/_ops_backups/`(可 restore)。
* **uid path-safe guard** + 預設要求 user 已存在(`user-create` / `restore` 除外)。
* **落地後讀回驗證** + append 到 `_ops_edit_audit.jsonl`。

寫入一律走 app 的 per-user store(`CardStore`/`GraphStore`/`NotebookStore`)——
NFC 正規化 / unique index / graph filelock merge 都是它們的 SoT,本檔不重刻。
容器內 `PYTHONPATH=/app/src` 使 `import kg.*` 可用;`KG_DATA_DIR` 切資料根
(dogfooding 注入 sandbox dir 即可零生產風險地完整演練)。
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from filelock import FileLock

from kg.cards import CardStore
from kg.cards.model import Card
from kg.graph.models import LinkKind
from kg.notebook import NotebookStore
from kg.ops_edit_shared import (
    EditContext,
    EditError,
    assert_safe_uid,
    emit,
    list_user_backups,
    user_dir_for,
    users_file,
    users_lock_file,
)
from kg.ops_shared import data_dir
from kg.user_store import load_users_from, save_users_to

_VALID_REVIEW_STATES = ("new", "due", "reviewed")

# `card-update --set` 的可寫欄位白名單。`CardStore.update` 本身用 hasattr 放行
# **任何**模型欄位(含 id / is_deleted / notebook_id / content_nfc_lower /
# timestamps),CLI 層必須收斂成明確白名單,否則 operator 可注入主鍵、繞過
# card-delete 軟刪、把卡移到不存在的筆記本。複習態走 `card-set-review`(語意
# sugar)、刪除走 `card-delete`,故 review_* 與 is_deleted 刻意不在白名單。
_CARD_UPDATABLE_FIELDS = frozenset({
    "content", "meaning", "pos", "examples", "collocations",
    "note", "difficulty", "mode", "root_form", "inflections",
})


def _passthrough_normalize(users: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """users.json 的 identity normalize:原樣讀寫,不碰 subscription/secret 加密。

    app 的 `normalize_users_payload` 需 `default_subscription_payload` + `encrypt_fn`
    (啟動期 wiring 的事);建/改 demo user record 與那些無關。passthrough 讓我們
    複用 `save_users_to` 的 atomic tmp→replace 寫入,同時**完整保留**既有 record
    的任何欄位(subscription / linked_ids / secret …),不破壞。
    """
    return users, False


# ── store helpers ──────────────────────────────────────────


def _card_store(user_dir: Path) -> CardStore:
    return CardStore(user_dir / "cards.db")


def _notebook_store(user_dir: Path) -> NotebookStore:
    return NotebookStore(user_dir / "notebooks.db")


def _graph_store(user_dir: Path, notebook_id: str = "default"):
    # function-level import:graph 路徑解析含 default-notebook legacy 遷移,
    # 借用 service_factories(它順帶 import embeddings/numpy);card/notebook
    # 操作不需要它,故不在 module top import,免無謂拉重依賴。
    from kg.service_factories import create_graph_store

    return create_graph_store(user_dir, notebook_id)


def _card_brief(card: Card) -> dict[str, Any]:
    return {
        "id": card.id,
        "content": card.content,
        "meaning": card.meaning,
        "pos": card.pos,
        "notebook_id": card.notebook_id,
        "review_count": card.review_count,
        "next_review_at": card.next_review_at,
        "last_review_feedback": card.last_review_feedback,
    }


def _split_multi(raw: str | None) -> list[str]:
    """CSV 風格多值:`a|b|c` → ['a','b','c'];空字串 → []。"""
    if not raw:
        return []
    return [s for s in (part.strip() for part in raw.split("|")) if s]


def _assert_clean_notebook_name(name: str) -> None:
    """notebook name 基本 sanity:非空、無控制字元、不過長。

    name 會顯示在 iOS UI 且被 seed 的 name→id 映射使用,放任 `\\n` / 超長 /
    `../../x` 類字串進來會傷 demo 帳號品質與映射可讀性。graph 檔路徑用隨機 hex id
    故無路徑逃逸,但路徑符號(`/` `\\` NUL)進到 name 仍是髒值(iOS 顯示異常、
    audit 可讀性差),一併擋掉。
    """
    if not name or not name.strip():
        raise EditError("notebook name 不可空白")
    if any(ord(ch) < 0x20 for ch in name):
        raise EditError("notebook name 不可含控制字元(換行/tab 等)")
    if any(ch in name for ch in ("/", "\\", "\x00")):
        raise EditError("notebook name 不可含路徑符號(/ \\ NUL)")
    if len(name) > 100:
        raise EditError(f"notebook name 過長(>100 chars):{len(name)}")


def _review_fields(state: str, interval_hours: float | None, now: datetime) -> dict[str, Any]:
    """把語意化的複習態映成 card 欄位(spaced-review state)。

    new       —— 從未複習(生詞庫「未學習」桶)。
    due       —— 已學過、現在到期(next_review_at 在過去,TodayReview 會撈)。
    reviewed  —— 剛複習完、下次在未來(「已複習」桶)。

    未知 state **fail-loud** raise(而非靜默落入 else 兜底成 reviewed):dogfood
    抓到 seed 路徑把 `{"state":"bogus"}` 當 reviewed 寫入,無聲污染複習態分布。
    在此 defense-in-depth 一次根治所有呼叫端(seed / card-add / card-set-review)。
    """
    if state not in _VALID_REVIEW_STATES:
        raise EditError(
            f"未知複習態 {state!r}(僅允許 {_VALID_REVIEW_STATES})"
        )
    # interval 須 > 0:負/零會讓 due 的 last_reviewed 落到未來、reviewed 的 next_review
    # 落到過去,破壞「reviewed→next 在未來」「due→last 在過去」不變量。argparse type=float
    # 不擋負值,在此一次根治所有呼叫端(card-add/card-set-review/card-import/seed)。
    if interval_hours is not None and interval_hours <= 0:
        raise EditError(f"複習間隔須 > 0 小時,得到 {interval_hours}")
    if state == "new":
        return {
            "review_count": 0,
            "review_streak": 0,
            "lapse_count": 0,
            "next_review_at": None,
            "last_reviewed_at": None,
            "last_review_feedback": -1,
            "review_interval_hours": interval_hours or 12.0,
        }
    iv = interval_hours or (12.0 if state == "due" else 24.0)
    if state == "due":
        # 內部自洽:last_reviewed + interval == next_review,且 next_review 落在
        # 過去(now - 1h)確保 TodayReview 撈得到。故 last = now - (iv + 1h)。
        last = now - timedelta(hours=iv + 1)
        return {
            "review_count": 1,
            "review_streak": 1,
            "lapse_count": 0,
            "last_reviewed_at": last,
            "next_review_at": last + timedelta(hours=iv),  # == now - 1h,已到期且自洽
            "last_review_feedback": 1,
            "review_interval_hours": iv,
        }
    # reviewed
    return {
        "review_count": 2,
        "review_streak": 2,
        "lapse_count": 0,
        "last_reviewed_at": now,
        "next_review_at": now + timedelta(hours=iv),
        "last_review_feedback": 1,
        "review_interval_hours": iv,
    }


def _as_utc(dt: datetime) -> datetime:
    """把 store 讀回的 datetime 統一成 aware UTC。

    SQLModel/SQLAlchemy 的 DateTime 欄位不存時區,寫入 aware、讀回 **naive**;
    直接拿讀回值與 `datetime.now(UTC)` 比較會炸 TypeError(naive vs aware)。
    naive 視為 UTC(寫入端一律 UTC),aware 原樣。
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _resolve_card_id(store: CardStore, ref: str, notebook_id: str | None = None) -> Card:
    """把 card 參照(id 或 content)解析成 Card。找不到 raise EditError。"""
    card = store.get(ref)
    if card and not card.is_deleted:
        return card
    card = store.find_by_content(ref, notebook_id=notebook_id)
    if card and not card.is_deleted:
        return card
    raise EditError(f"card not found: {ref!r}(既非 id 也非現存 content)")


def _resolve_card_in_notebook(store: CardStore, ref: str, notebook_id: str) -> Card:
    """同本解析 link 端點 card(id 或 content),嚴格限定在 ``notebook_id`` 內。

    KG 圖譜是 **per-notebook**,link 兩端必須同本(graph_<nb>.json 只裝該本的 link)。
    故 link 場景的 card 解析不可跨本 fallback。卡在別本時給精準錯誤(而非籠統
    「card not found」),引導 operator 把 card 與 link 對齊到同一 notebook。
    link-add 與 seed 的 link 解析共用。
    """
    card = store.get(ref)
    if card and not card.is_deleted and card.notebook_id == notebook_id:
        return card
    card = store.find_by_content(ref, notebook_id=notebook_id)
    if card and not card.is_deleted:
        return card
    elsewhere = store.find_by_content(ref, notebook_id=None)
    if elsewhere is not None and not elsewhere.is_deleted:
        raise EditError(
            f"card {ref!r} 在別的 notebook({elsewhere.notebook_id}),但 link 兩端須與 link "
            f"同在 notebook {notebook_id}(圖譜為 per-notebook,不支援跨本 link)"
        )
    raise EditError(f"card not found in notebook {notebook_id}: {ref!r}")


def _resolve_notebook_id(user_dir: Path, ref: str) -> str:
    """把 notebook 參照(name 或 id)解析成實際 notebook id。

    operator 直覺會傳 name(「Classic Literature」),但 `CardStore.add` 把 notebook_id
    原樣存進 DB —— 傳 name 會建出 iOS 任何視圖都查不到的**孤兒卡**(dogfood A HIGH-2)。
    此處統一解析:`"default"` / 既存 name / 既存 id → id;否則 fail-loud,絕不靜默把
    name 當 id 存。card-add / card-import / link-add / card-move 共用,語意對齊 seed 的
    `_resolve_nb`。name 撞多本時取 `NotebookStore.all()` 排序首筆(sort_order, created_at)。
    """
    if ref == "default":
        return "default"
    store = _notebook_store(user_dir)
    # id 精確匹配**優先**於 name 掃描:若某本 name 恰好等於另一本的 hex id,傳該 id
    # 字串應解析成 id 那本,而非 name 那本(dogfood D HIGH-3)。id 是 primary key,
    # get(name) 必為 None,故 exists() 只對真正的 id 為真,不會誤吞 name。
    if store.exists(ref):
        return ref
    for nb in store.all():
        if nb.name == ref:
            return nb.id
    raise EditError(
        f"notebook not found: {ref!r}(既非既存 id 也非既存 name;先 notebook-create)"
    )


def _link_on_disk(graph: Any, link_id: str) -> bool:
    """直接讀 ``graph.links_path`` 的 JSON,確認 link 真的落盤(繞過進程內快取)。

    `create_graph_store` 走 `_get_cached`,apply 與 verify 拿**同一實例**;`get_link`
    讀記憶體 `_links`,若 `_flush_links` 靜默寫失敗,verify 仍報綠(dogfood C1 的架構級
    false-green)。改讀磁碟 JSON,verify 的綠才等於磁碟真相。links 檔可能是 list 或
    以 id 為鍵的 dict,兩種形狀都認。
    """
    p = graph.links_path
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    entries = data if isinstance(data, list) else list(data.values()) if isinstance(data, dict) else []
    return any(isinstance(e, dict) and e.get("id") == link_id for e in entries)


# ── users.json 編輯(共用 app 的 load/save + FileLock) ──


def _mutate_users(data_dir_path: Path, mutate) -> dict[str, Any]:
    """在 app 的 users.json 寫鎖下 load→mutate→save。回傳 mutate 的結果。"""
    uf = users_file(data_dir_path)
    with FileLock(str(users_lock_file(data_dir_path))):
        users = load_users_from(uf, _passthrough_normalize) if uf.exists() else {}
        result = mutate(users)
        save_users_to(uf, users, _passthrough_normalize)
    return result


# ── 子指令 ─────────────────────────────────────────────────


def cmd_user_create(args: argparse.Namespace) -> int:
    uid = args.uid
    assert_safe_uid(uid)
    dd = data_dir()
    uf = users_file(dd)
    existing_users = load_users_from(uf, _passthrough_normalize) if uf.exists() else {}
    already = uid in existing_users or user_dir_for(dd, uid).exists()

    plan = {
        "uid": uid,
        "provider": args.provider,
        "email": args.email,
        "already_exists": already,
        "creates_dir": str(user_dir_for(dd, uid)),
    }

    if already and not args.allow_existing:
        emit(
            {"mode": "error", "action": "user-create", "uid": uid, "plan": plan,
             "committed": False,
             "error": "user 已存在;確認後加 --allow-existing 才會 merge record"},
            json_mode=args.json,
        )
        return 1

    ctx = EditContext(data_dir=dd, uid=uid, commit=args.commit,
                      json_mode=args.json, require_user=False)

    def apply_fn() -> dict[str, Any]:
        now = datetime.now(tz=UTC).isoformat()

        def mutate(users: dict[str, Any]) -> dict[str, Any]:
            # 鎖內重判存在性:L?? 的 early read 在 FileLock 外,兩個並發
            # user-create 可能都讀到「不存在」再雙雙進鎖覆寫。鎖內 re-check 關掉
            # 這個 TOCTOU —— 第二個進鎖者若發現已存在且未 --allow-existing 即中止。
            if uid in users and not args.allow_existing:
                raise EditError(
                    "user 已存在(鎖內偵測);加 --allow-existing 才會 merge record"
                )
            idx = users.setdefault("_email_index", {})
            record = users.get(uid, {}) if isinstance(users.get(uid), dict) else {}
            record.setdefault("config", {})
            record["provider"] = args.provider
            if args.email:
                record["email"] = args.email
                idx[args.email] = uid
            record.setdefault("created_at", now)
            record["last_login"] = now
            users[uid] = record
            return record

        record = _mutate_users(dd, mutate)
        user_dir_for(dd, uid).mkdir(parents=True, exist_ok=True)
        # 建好預設筆記本,讓帳號一登入就有 default notebook。
        _notebook_store(user_dir_for(dd, uid)).ensure_default()
        return {"record": record}

    def verify_fn() -> dict[str, Any]:
        users = load_users_from(uf, _passthrough_normalize)
        return {"ok": uid in users and user_dir_for(dd, uid).exists()}

    return ctx.run(action="user-create", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)


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
        link = graph.add_link(
            from_id=from_card.id, to_id=to_card.id,
            kind=LinkKind(args.kind), confidence=args.confidence, reason=args.reason,
        )
        state["link_id"] = link.id
        is_idem = pre_existing is not None and pre_existing.id == link.id
        return {"link": {"id": link.id, "from": from_card.content, "to": to_card.content,
                         "kind": str(link.kind), "confidence": link.confidence},
                "idempotent": is_idem}

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
        from_id, to_id = graph.hard_delete_link(args.link_id)
        return {"deleted_link": args.link_id, "from_id": from_id, "to_id": to_id}

    def verify_fn() -> dict[str, Any]:
        # 讀磁碟確認 link 已從盤上移除(繞快取記憶體,dogfood C1)。
        graph = _graph_store(ctx.user_dir, nb_id)
        return {"ok": not _link_on_disk(graph, args.link_id)}

    return ctx.run(action="link-delete", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)


def cmd_seed(args: argparse.Namespace) -> int:
    """一次性把 notebooks + cards + links 整套灌入(mock/demo 帳號用)。

    spec JSON 結構:
      {
        "notebooks": [{"name", "color"?, "cover_pattern"?}],
        "cards": [{"content","meaning","pos"?,"examples"?,"collocations"?,
                   "note"?,"difficulty"?,"mode"?,"notebook"?,
                   "review"?: {"state":"new|due|reviewed","interval"?}}],
        "links": [{"from","to","kind","confidence","reason","notebook"?}]
      }
    cards/links 的 "notebook" 可指 spec 建立的、或**既存的** notebook name / id;
    links 的 from/to 用 card content 參照(seed 內先建卡再連結)。
    """
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    spec_path = Path(args.spec)
    if not spec_path.exists():
        raise EditError(f"spec not found: {spec_path}")
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # 非 JSON spec 此前讓 raw traceback 污染 --json stdout(dogfood B3);轉成
        # 結構化 EditError,維持「stdout 只有合法 JSON」的契約。
        raise EditError(f"spec JSON 解析失敗:{exc}") from exc
    if not isinstance(spec, dict):
        raise EditError("spec 頂層須為 JSON object(含 notebooks/cards/links 鍵)")
    notebooks = spec.get("notebooks", [])
    cards = spec.get("cards", [])
    links = spec.get("links", [])

    # 預驗(寫入前,確保原子性):任何缺漏在動 DB 前就 raise,不留孤兒 notebook。
    def _prevalidate() -> None:
        seen_names: set[str] = set()
        for i, n in enumerate(notebooks):
            name = n.get("name") or ""
            _assert_clean_notebook_name(name)
            # spec 內重複 notebook name 會建出多本同名、name→id 映射被後者覆蓋、
            # 前者成孤兒(dogfood A MED-2);寫入前擋掉。
            if name in seen_names:
                raise EditError(f"notebooks 有重複 name:{name!r}")
            seen_names.add(name)
        for i, c in enumerate(cards):
            if not (c.get("content") or "").strip():
                raise EditError(f"cards[{i}] content 空白:{c!r}")
            # meaning 空白與 card-import 一致擋掉:demo 卡需有定義(dogfood A MED-1)。
            if not (c.get("meaning") or "").strip():
                raise EditError(f"cards[{i}] meaning 空白:{c.get('content')!r}")
            # review.state 非法值 fail-loud,而非靜默當 reviewed(dogfood B5 / A LOW-1)。
            rv = c.get("review")
            if isinstance(rv, dict):
                st = rv.get("state")
                if st not in (None, "") and st not in _VALID_REVIEW_STATES:
                    raise EditError(f"cards[{i}] review.state 非法:{st!r}(僅 {_VALID_REVIEW_STATES})")
        for i, lk in enumerate(links):
            for k in ("from", "to", "kind", "confidence", "reason"):
                if lk.get(k) in (None, ""):
                    raise EditError(f"links[{i}] 缺 {k}:{lk!r}")
            if lk["kind"] not in (LinkKind.CONTRASTS_WITH, LinkKind.SHARES_USAGE):
                raise EditError(f"links[{i}] kind 非法:{lk['kind']!r}")
            try:
                conf = float(lk["confidence"])
            except (TypeError, ValueError) as exc:
                raise EditError(f"links[{i}] confidence 非數值:{lk['confidence']!r}") from exc
            if not 0.0 <= conf <= 1.0:
                raise EditError(f"links[{i}] confidence 須在 0.0~1.0:{conf}")

    # 在 plan 計算前就驗 —— dry-run 也能提前報格式錯誤,不必等 --commit 才爆
    # (dogfood E F7)。_prevalidate 純檢查無副作用,前移安全。
    _prevalidate()

    dist = {"new": 0, "due": 0, "reviewed": 0, "unspecified": 0}
    for c in cards:
        rv = c.get("review")
        st = rv.get("state") if isinstance(rv, dict) else None
        dist[st if st in _VALID_REVIEW_STATES else "unspecified"] += 1
    plan = {
        "notebooks": len(notebooks), "cards": len(cards), "links": len(links),
        "notebook_names": [n.get("name") for n in notebooks],
        "card_sample": [c.get("content") for c in cards[:5]],
        "link_sample": [f'{l.get("from")}→{l.get("to")} ({l.get("kind")})' for l in links[:3]],
        "review_distribution": dist,
    }

    seed_state: dict[str, Any] = {}

    def apply_fn() -> dict[str, Any]:
        # _prevalidate() 已在 plan 前跑過(dry-run 也驗);此處不重複。
        now = datetime.now(tz=UTC)
        nb_store = _notebook_store(ctx.user_dir)
        nb_store.ensure_default()
        # name → id 映射。**先納入所有既存 notebook**(operator 可能先
        # notebook-create 再 seed,cards 用既存 name 指筆記本,不可 fallback 成把
        # name 字串當 notebook_id 存),spec 建立的覆蓋同名既存。
        name_to_id = {"default": "default"}
        for nb in nb_store.all():
            name_to_id[nb.name] = nb.id
        existing_ids = {nb.id for nb in nb_store.all()}
        created_nb = []
        for n in notebooks:
            name = n["name"]
            # 冪等:同名既存(含上輪 seed 建立)直接重用,不重複新建(dogfood A MED-2/MED-4)。
            # seed 是「確保狀態」語意,重跑同 spec 結果應一致、不增殖孤兒 notebook。
            if name in name_to_id:
                created_nb.append({"id": name_to_id[name], "name": name, "reused": True})
                continue
            nb = nb_store.create(name=name, color=n.get("color"),
                                 cover_pattern=n.get("cover_pattern"))
            name_to_id[name] = nb.id
            existing_ids.add(nb.id)
            created_nb.append({"id": nb.id, "name": name})

        def _resolve_nb(ref: str) -> str:
            # 接受:已知 name、直接給的合法既存 id;否則明確報錯(不靜默存 name)。
            if ref in name_to_id:
                return name_to_id[ref]
            if ref in existing_ids:
                return ref
            raise EditError(
                f"seed 指向不存在的 notebook {ref!r}(既非 spec 建立、也非既存 name/id)"
            )

        card_store = _card_store(ctx.user_dir)
        # 真實新增數用 pre/post id diff(對齊 card-import)——CardStore.add 對既有
        # content 冪等回舊卡,無腦 +=1 會把 dup 誤報成新增(dogfood C3)。
        pre_ids = {c.id for c in card_store.all()}
        card_checks: list[dict[str, Any]] = []
        for c in cards:
            nb_id = _resolve_nb(c.get("notebook", "default"))
            card = card_store.add(
                content=c["content"], meaning=c.get("meaning", ""),
                pos=c.get("pos"), examples=c.get("examples") or [],
                collocations=c.get("collocations") or [],
                mode=c.get("mode", "recognition"), notebook_id=nb_id,
            )
            # dup 卡也 upsert 核心欄位:add 對既有 content 回舊卡、**不更新** meaning,
            # 但 seed 須冪等可重跑(調 spec 再灌)→ 顯式覆蓋 meaning/pos/examples/... ,
            # 否則改了 spec 卻靜默沿用舊值(dogfood C2 false-green)。新卡此處冗餘覆蓋
            # 無害(CardStore.update 有 has_changes 檢查,值同不寫)。
            #
            # 用 `key in c` 而非 `c.get(key)` 判斷:區分「spec 省略該欄」(保留舊值)與
            # 「spec 明確設空 [] / null」(清空)。`if c.get("examples")` 會把 [] 當 falsy
            # 漏掉,讓 operator 無法用 seed 清空欄位(dogfood D MED-2)。
            updates: dict[str, Any] = {"meaning": c.get("meaning", "")}
            if "pos" in c:
                updates["pos"] = c["pos"]
            if "examples" in c:
                updates["examples"] = c["examples"] or []
            if "collocations" in c:
                updates["collocations"] = c["collocations"] or []
            if c.get("mode"):
                updates["mode"] = c["mode"]
            if "note" in c:
                updates["note"] = c["note"]
            if "difficulty" in c:
                updates["difficulty"] = c["difficulty"]
            rv = c.get("review")
            if isinstance(rv, dict) and rv.get("state"):
                updates.update(_review_fields(rv["state"], rv.get("interval"), now))
            card_store.update(card.id, **updates)
            card_checks.append({"content": c["content"].strip(), "nb_id": nb_id,
                                "meaning": c.get("meaning", "")})
        seed_state["card_checks"] = card_checks
        post_ids = {c.id for c in card_store.all()}
        actually_new = len(post_ids - pre_ids)

        added_links = 0
        link_errors: list[str] = []
        for lk in links:
            nb_id = _resolve_nb(lk.get("notebook", "default"))
            try:
                # link 嚴格同本:圖譜為 per-notebook,link 兩端 card 必須與 link 同在
                # nb_id。card 不在該本 → spec 不一致,_resolve_card_in_notebook 給精準
                # 錯誤(指出 card 在哪本)引導修 spec,而非全局硬連成跨本 link。
                from_card = _resolve_card_in_notebook(card_store, lk["from"], nb_id)
                to_card = _resolve_card_in_notebook(card_store, lk["to"], nb_id)
                graph = _graph_store(ctx.user_dir, nb_id)
                graph.add_link(from_id=from_card.id, to_id=to_card.id, kind=LinkKind(lk["kind"]),
                               confidence=float(lk["confidence"]), reason=lk["reason"])
                added_links += 1
            except (EditError, ValueError, KeyError) as exc:
                link_errors.append(f"{lk.get('from')}→{lk.get('to')}: {exc}")

        seed_state["link_errors"] = link_errors
        return {"notebooks_created": created_nb, "cards_added": actually_new,
                "skipped_dup": len(cards) - actually_new,
                "links_added": added_links, "link_errors": link_errors}

    def verify_fn() -> dict[str, Any]:
        card_store = _card_store(ctx.user_dir)
        total = card_store.count()
        errs = seed_state.get("link_errors", [])
        # 抽驗每張 spec 卡的 meaning 真的落盤,獵殺 dup 卡 upsert 沒生效卻報綠的
        # false-green(dogfood C2)。按 (content, **resolved nb_id**) 精確比對 —— 用
        # notebook_id=None 全局查會在跨本同名卡時只找到第一張、誤報 mismatch(dogfood
        # D MED-1,我上輪引入的回歸)。
        field_mismatches: list[str] = []
        for chk in seed_state.get("card_checks", []):
            found = card_store.find_by_content(chk["content"], notebook_id=chk["nb_id"])
            if found is None:
                field_mismatches.append(f"{chk['content']}@{chk['nb_id']}: missing")
            elif chk["meaning"] and found.meaning != chk["meaning"]:
                field_mismatches.append(f"{chk['content']}@{chk['nb_id']}: meaning not applied")
        # link 失敗 / 欄位未落盤都算 verify 失敗 —— 否則無聲失敗報 ok。
        return {"ok": total >= len(cards) and not errs and not field_mismatches,
                "total_cards": total, "link_errors": errs,
                "field_mismatches": field_mismatches[:5]}

    return ctx.run(action="seed", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)


def cmd_list_backups(args: argparse.Namespace) -> int:
    dd = data_dir()
    assert_safe_uid(args.uid)
    backups = list_user_backups(dd, args.uid)
    emit({"action": "list-backups", "uid": args.uid, "count": len(backups),
          "backups": backups}, json_mode=args.json)
    return 0


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


def cmd_restore(args: argparse.Namespace) -> int:
    """從備份還原 user_dir。commit 前 EditContext 會先備份**當前**狀態,故可回退。"""
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit,
                      json_mode=args.json, require_user=False)
    backups = list_user_backups(dd, args.uid)
    if args.backup:
        backup_path = Path(args.backup)
        if not backup_path.exists():
            raise EditError(f"指定的備份不存在:{backup_path}")
    else:
        if not backups:
            raise EditError(f"無備份可還原(data_dir/_ops_backups/ 下無 {args.uid}__*.tar.gz)")
        backup_path = Path(backups[0]["path"])  # 最新

    with tarfile.open(backup_path) as tar:
        names = tar.getnames()
    # B1:備份 tar 頂層目錄必須 == uid。指向他人 uid 的備份會在 rmtree 掉 target
    # user_dir 後、把內容解壓到別的目錄,**靜默消滅** target(dogfood B1)。在動任何
    # 檔案前(rmtree 之前)擋掉 arcname 不符的備份。
    top_dirs = {n.split("/")[0] for n in names if n and not n.startswith("/")}
    if top_dirs != {args.uid}:
        raise EditError(
            f"備份 arcname 與 uid 不符:tar 頂層={sorted(top_dirs)},預期僅 "
            f"{{{args.uid!r}}};拒絕還原(避免消滅 target user_dir)"
        )
    db_files = [n for n in names if n.endswith(".db")]
    graph_files = [n for n in names if n.endswith(".json")]
    plan = {"restore_from": str(backup_path), "target_dir": str(ctx.user_dir),
            "available_backups": len(backups), "total_members": len(names),
            "db_files": len(db_files), "graph_files": len(graph_files),
            "sample_members": names[:10]}

    def apply_fn() -> dict[str, Any]:
        # EditContext 已在此之前備份了當前 user_dir(若存在),所以即使還原錯版本
        # 也能再 restore 回來。先清掉現狀再解壓,避免新舊檔殘留混雜。
        if ctx.user_dir.exists():
            shutil.rmtree(ctx.user_dir)
        # tar 內 arcname=uid,解壓到 users/ 還原成 users/<uid>/。
        # filter='data' 擋絕對路徑 / .. 逃逸(備份雖自產,仍守一道)。
        with tarfile.open(backup_path) as tar:
            tar.extractall(ctx.user_dir.parent, filter="data")
        return {"restored_from": str(backup_path)}

    def verify_fn() -> dict[str, Any]:
        # 放寬:早期快照(user-create 後、首次 card 操作前)只含 notebooks.db、無
        # cards.db,屬正常合法狀態,不該判失敗(dogfood A HIGH-1)。user_dir 在 + 至少
        # notebooks.db 在即視為成功還原。
        return {"ok": ctx.user_dir.exists() and (ctx.user_dir / "notebooks.db").exists()}

    return ctx.run(action="restore", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)


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
    if not updates:
        raise EditError("notebook-update 需至少一個 --name / --color / --cover")
    plan = {"notebook_id": nb_id, "updates": updates}

    def apply_fn() -> dict[str, Any]:
        store = _notebook_store(ctx.user_dir)
        nb = store.update(nb_id, **updates)
        if nb is None:
            raise EditError(f"notebook not found 或已刪除:{nb_id}")
        return {"notebook": {"id": nb.id, "name": nb.name, "color": nb.color,
                             "cover_pattern": nb.cover_pattern}}

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
                graph.hard_delete_link(lk.id)
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
        lk = graph.update_link(args.link_id, **updates)
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


# ── argparse ───────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ops_edit.py", description="KG production 資料**寫入**工具(dry-run 預設)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # 共用 parents:--json(機讀) / --commit(真寫,否則 dry-run)。
    jp = argparse.ArgumentParser(add_help=False)
    jp.add_argument("--json", action="store_true", help="以 JSON 輸出")
    cp = argparse.ArgumentParser(add_help=False)
    cp.add_argument("--commit", action="store_true",
                    help="真正寫入(預設 dry-run 只印 plan)")

    p = sub.add_parser("user-create", parents=[jp, cp], help="建立用戶 + 預設筆記本")
    p.add_argument("uid")
    p.add_argument("--email")
    p.add_argument("--provider", default="google", choices=["google", "apple", "demo"])
    p.add_argument("--allow-existing", action="store_true", help="user 已存在時 merge record")
    p.set_defaults(func=cmd_user_create)

    p = sub.add_parser("card-add", parents=[jp, cp], help="新增單字卡")
    p.add_argument("uid")
    p.add_argument("content")
    p.add_argument("--meaning", required=True)
    p.add_argument("--pos")
    p.add_argument("--example", action="append", help="例句(可重複)")
    p.add_argument("--collocation", action="append", help="搭配(可重複)")
    p.add_argument("--note")
    p.add_argument("--difficulty", type=float)
    p.add_argument("--mode", default="recognition", choices=["recognition", "production"])
    p.add_argument("--notebook", default="default")
    p.add_argument("--review", choices=list(_VALID_REVIEW_STATES))
    p.add_argument("--interval", type=float, help="複習間隔(小時)")
    p.set_defaults(func=cmd_card_add)

    p = sub.add_parser("card-update", parents=[jp, cp], help="改卡欄位(--set field=value)")
    p.add_argument("uid")
    p.add_argument("card", help="card id 或 content")
    p.add_argument("--set", action="append", help="field=value(value 走 JSON 解析;可重複)")
    p.set_defaults(func=cmd_card_update)

    p = sub.add_parser("card-set-review", parents=[jp, cp], help="設複習態(new/due/reviewed)")
    p.add_argument("uid")
    p.add_argument("card", help="card id 或 content")
    p.add_argument("--state", required=True, choices=list(_VALID_REVIEW_STATES))
    p.add_argument("--interval", type=float)
    p.set_defaults(func=cmd_card_set_review)

    p = sub.add_parser("card-delete", parents=[jp, cp], help="軟刪單字卡")
    p.add_argument("uid")
    p.add_argument("card", help="card id 或 content")
    p.set_defaults(func=cmd_card_delete)

    p = sub.add_parser("card-import", parents=[jp, cp], help="CSV 批量匯入(card_format.md 格式)")
    p.add_argument("uid")
    p.add_argument("csv", help="CSV 檔路徑")
    p.add_argument("--notebook", default="default")
    p.set_defaults(func=cmd_card_import)

    p = sub.add_parser("notebook-create", parents=[jp, cp], help="建立筆記本")
    p.add_argument("uid")
    p.add_argument("name")
    p.add_argument("--color")
    p.add_argument("--cover", help="cover_pattern")
    p.set_defaults(func=cmd_notebook_create)

    p = sub.add_parser("link-add", parents=[jp, cp], help="連結兩張卡(知識圖譜)")
    p.add_argument("uid")
    p.add_argument("from_ref", metavar="from", help="來源 card id 或 content")
    p.add_argument("to_ref", metavar="to", help="目標 card id 或 content")
    p.add_argument("--kind", required=True, choices=["contrasts_with", "shares_usage"])
    p.add_argument("--confidence", type=float, required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--notebook", default="default")
    p.set_defaults(func=cmd_link_add)

    p = sub.add_parser("link-delete", parents=[jp, cp], help="硬刪一條連結")
    p.add_argument("uid")
    p.add_argument("link_id")
    p.add_argument("--notebook", default="default")
    p.set_defaults(func=cmd_link_delete)

    p = sub.add_parser("seed", parents=[jp, cp], help="一次性灌整套 demo(notebooks+cards+links)")
    p.add_argument("uid")
    p.add_argument("spec", help="seed spec JSON 檔路徑")
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser("list-backups", parents=[jp], help="列出某 uid 的自動備份(最新在前)")
    p.add_argument("uid")
    p.set_defaults(func=cmd_list_backups)

    p = sub.add_parser("restore", parents=[jp, cp], help="從備份還原 user_dir(預設取最新)")
    p.add_argument("uid")
    p.add_argument("--backup", help="指定備份 tar.gz 路徑(預設取最新)")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("notebook-update", parents=[jp, cp], help="改筆記本 name/color/cover")
    p.add_argument("uid")
    p.add_argument("notebook", help="notebook id 或 name")
    p.add_argument("--name")
    p.add_argument("--color")
    p.add_argument("--cover", help="cover_pattern")
    p.set_defaults(func=cmd_notebook_update)

    p = sub.add_parser("notebook-delete", parents=[jp, cp], help="軟刪筆記本(default 不可刪)")
    p.add_argument("uid")
    p.add_argument("notebook", help="notebook id 或 name")
    p.add_argument("--cascade", action="store_true",
                   help="一併軟刪該本所有卡(否則非空時拒絕,避免孤兒卡)")
    p.set_defaults(func=cmd_notebook_delete)

    p = sub.add_parser("card-move", parents=[jp, cp], help="把卡移到別的筆記本")
    p.add_argument("uid")
    p.add_argument("card", help="card id 或 content")
    # --notebook 為 --to-notebook 的 alias:與全工具 --notebook 慣例一致(dogfood E F2)。
    p.add_argument("--to-notebook", "--notebook", dest="to_notebook", required=True,
                   help="目標 notebook id 或 name")
    p.set_defaults(func=cmd_card_move)

    p = sub.add_parser("link-list", parents=[jp], help="列出某 notebook 的連結(id+兩端 content)")
    p.add_argument("uid")
    p.add_argument("--notebook", default="default")
    p.set_defaults(func=cmd_link_list)

    p = sub.add_parser("link-update", parents=[jp, cp], help="改連結 confidence/reason/kind")
    p.add_argument("uid")
    p.add_argument("link_id")
    p.add_argument("--confidence", type=float)
    p.add_argument("--reason")
    p.add_argument("--kind", choices=["contrasts_with", "shares_usage"])
    p.add_argument("--notebook", default="default")
    p.set_defaults(func=cmd_link_update)

    args = parser.parse_args()
    try:
        code = args.func(args)
    except EditError as exc:
        emit({"mode": "error", "action": args.cmd, "error": str(exc), "committed": False},
             json_mode=getattr(args, "json", False))
        sys.exit(1)
    sys.exit(code or 0)


if __name__ == "__main__":
    main()
