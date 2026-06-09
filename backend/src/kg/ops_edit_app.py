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
import hashlib
import json
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from filelock import FileLock

from kg.api_models.common import VocabSource
from kg.api_models.notebook import VocabUIConfig
from kg.api_models.review import ReviewClockConfig, ReviewModeConfig
from kg.api_models.translate import TranslationLanguageConfig
from kg.cards import CardStore
from kg.cards.model import Card
from kg.demo_review_synth import CardReviewState, synthesize_many
from kg.graph.models import LinkKind
from kg.notebook import NotebookStore
from kg.review_events import ReviewEventStore
from kg.ops_edit_shared import (
    EditContext,
    EditError,
    assert_safe_uid,
    backup_world,
    emit,
    list_user_backups,
    world_backup_root,
    user_dir_for,
    users_file,
    users_lock_file,
)
from kg.ops_world_projection import project_user_world
from kg.ops_shared import data_dir
from kg.user_store import load_users_from, parse_datetime, save_users_to

_VALID_REVIEW_STATES = ("new", "due", "reviewed")
_USER_BACKUP_META_DIR = ".ops_meta"
_USER_BACKUP_RECORD = "user_record.json"
_USER_BACKUP_EMAIL_INDEX = "email_index.json"
_WORLD_BACKUP_ROOT = "__kg_world__"

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


def _parse_seed_datetime(raw: Any, label: str) -> datetime | None:
    parsed = parse_datetime(raw)
    if raw is not None and parsed is None:
        raise EditError(f"{label} 必須是 ISO datetime 或 Unix timestamp:{raw!r}")
    return parsed


def _source_to_json(raw: Any, label: str) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        if not raw.strip():
            return None
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EditError(f"{label} 字串必須是 VocabSource JSON object") from exc
    if not isinstance(raw, dict):
        raise EditError(f"{label} 必須是 VocabSource object 或 JSON string")
    try:
        source = VocabSource(**raw)
    except Exception as exc:
        raise EditError(f"{label} 不符合 VocabSource schema:{exc}") from exc
    return source.model_dump_json(exclude_none=True)


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


def _restore_user_record_snapshot(data_dir_path: Path, uid: str, *, record: dict[str, Any] | None,
                                  email_index: dict[str, Any] | None) -> None:
    """把 per-user backup 內嵌的 users.json snapshot merge 回目前 users.json。

    restore 粒度是「單帳號」，所以不能用備份裡的整份 users.json 覆蓋現況；只回復
    target uid 的 record 與對應 email index 條目，避免誤傷其他帳號。
    """

    if record is None and not email_index:
        return

    def mutate(users: dict[str, Any]) -> dict[str, Any]:
        if record is not None:
            users[uid] = record
        idx = users.setdefault("_email_index", {})
        if not isinstance(idx, dict):
            idx = {}
            users["_email_index"] = idx
        stale = [email for email, mapped_uid in idx.items() if mapped_uid == uid]
        for email in stale:
            idx.pop(email, None)
        if email_index:
            for email, mapped_uid in email_index.items():
                if mapped_uid == uid:
                    idx[email] = uid
        return {"restored": uid}

    _mutate_users(data_dir_path, mutate)


def _extract_user_backup_members(tar: tarfile.TarFile, uid: str, target_parent: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    members = tar.getmembers()
    record: dict[str, Any] | None = None
    email_index: dict[str, Any] | None = None
    for member in members:
        name = member.name.lstrip("./")
        if name == f"{uid}/{_USER_BACKUP_META_DIR}/{_USER_BACKUP_RECORD}":
            fileobj = tar.extractfile(member)
            if fileobj is not None:
                data = json.loads(fileobj.read().decode("utf-8"))
                record = data if isinstance(data, dict) else None
            continue
        if name == f"{uid}/{_USER_BACKUP_META_DIR}/{_USER_BACKUP_EMAIL_INDEX}":
            fileobj = tar.extractfile(member)
            if fileobj is not None:
                data = json.loads(fileobj.read().decode("utf-8"))
                email_index = data if isinstance(data, dict) else None
            continue
        if f"/{_USER_BACKUP_META_DIR}/" in name:
            continue
        tar.extract(member, path=target_parent, filter="data")
    return record, email_index


def _world_members(data_dir_path: Path) -> list[Path]:
    excluded = {world_backup_root(data_dir_path).name, "_ops_backups", "_ops_edit_audit.jsonl", "users.json.lock"}
    return [p for p in sorted(Path(data_dir_path).iterdir()) if p.name not in excluded]


def _replace_world_from_snapshot(data_dir_path: Path, snapshot_root: Path) -> list[str]:
    removed: list[str] = []
    for existing in _world_members(data_dir_path):
        removed.append(existing.name)
        if existing.is_dir():
            shutil.rmtree(existing)
        else:
            existing.unlink()
    restored: list[str] = []
    for item in sorted(snapshot_root.iterdir()):
        dest = Path(data_dir_path) / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
        restored.append(item.name)
    return restored


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


def cmd_user_config_set(args: argparse.Namespace) -> int:
    """更新 users.json 內的 per-user config，供 marketing / mock surface 造景。"""
    dd = data_dir()
    ctx = EditContext(data_dir=dd, uid=args.uid, commit=args.commit, json_mode=args.json)
    now_epoch = datetime.now(tz=UTC).timestamp()
    updates: dict[str, Any] = {}

    if args.translation_source is not None or args.translation_target is not None:
        updates["translation"] = {
            "source_lang": args.translation_source,
            "target_lang": args.translation_target,
        }

    if args.paused_at is not None and args.review_clock != "paused":
        raise EditError("--paused-at 需搭配 --review-clock paused")
    if args.review_clock is not None:
        if args.paused_at is not None:
            if parse_datetime(args.paused_at) is None:
                raise EditError(f"--paused-at 必須是 ISO datetime 或 Unix timestamp:{args.paused_at!r}")
            paused_at = args.paused_at
        elif args.review_clock == "paused":
            paused_at = datetime.now(tz=UTC).isoformat()
        else:
            paused_at = None
        updates["review_clock"] = {
            "is_paused": args.review_clock == "paused",
            "paused_at": paused_at,
        }

    review_mode_fields = (
        args.review_mode,
        args.custom_initial_interval_hours,
        args.custom_remembered_multiplier,
        args.custom_forgot_multiplier,
        args.custom_minimum_interval_hours,
        args.custom_maximum_interval_hours,
    )
    if any(v is not None for v in review_mode_fields):
        updates["review_mode"] = {
            "mode": args.review_mode,
            "custom_initial_interval_hours": args.custom_initial_interval_hours,
            "custom_remembered_multiplier": args.custom_remembered_multiplier,
            "custom_forgot_multiplier": args.custom_forgot_multiplier,
            "custom_minimum_interval_hours": args.custom_minimum_interval_hours,
            "custom_maximum_interval_hours": args.custom_maximum_interval_hours,
        }

    resolved_nb_id = None
    if args.active_notebook is not None:
        resolved_nb_id = _resolve_notebook_id(ctx.user_dir, args.active_notebook)
        updates["vocab_ui"] = {"active_notebook_id": resolved_nb_id}

    if not updates:
        raise EditError(
            "user-config-set 需至少一個 translation/review_clock/review_mode/vocab_ui 相關旗標"
        )

    plan = {"updates": updates}
    state: dict[str, Any] = {}

    def apply_fn() -> dict[str, Any]:
        def mutate(users: dict[str, Any]) -> dict[str, Any]:
            record = users.get(args.uid, {}) if isinstance(users.get(args.uid), dict) else {}
            config = record.get("config", {}) if isinstance(record.get("config"), dict) else {}

            if "translation" in updates:
                current = config.get("translation", {}) if isinstance(config.get("translation"), dict) else {}
                translation = TranslationLanguageConfig(
                    source_lang=updates["translation"]["source_lang"] or current.get("source_lang", "en"),
                    target_lang=updates["translation"]["target_lang"] or current.get("target_lang", "zh-Hant"),
                    updated_at=now_epoch,
                )
                config["translation"] = {
                    "source_lang": translation.source_lang,
                    "target_lang": translation.target_lang,
                    "updated_at": translation.updated_at,
                }

            if "review_clock" in updates:
                clock = ReviewClockConfig(
                    is_paused=updates["review_clock"]["is_paused"],
                    paused_at=updates["review_clock"]["paused_at"],
                    updated_at=now_epoch,
                )
                config["review_clock"] = {
                    "is_paused": clock.is_paused,
                    "paused_at": clock.paused_at,
                    "updated_at": clock.updated_at,
                }

            if "review_mode" in updates:
                current = config.get("review_mode", {}) if isinstance(config.get("review_mode"), dict) else {}
                mode = ReviewModeConfig(
                    mode=updates["review_mode"]["mode"] or current.get("mode", "relaxed"),
                    custom_initial_interval_hours=(
                        updates["review_mode"]["custom_initial_interval_hours"]
                        if updates["review_mode"]["custom_initial_interval_hours"] is not None
                        else current.get("custom_initial_interval_hours", 12)
                    ),
                    custom_remembered_multiplier=(
                        updates["review_mode"]["custom_remembered_multiplier"]
                        if updates["review_mode"]["custom_remembered_multiplier"] is not None
                        else current.get("custom_remembered_multiplier", 1.9)
                    ),
                    custom_forgot_multiplier=(
                        updates["review_mode"]["custom_forgot_multiplier"]
                        if updates["review_mode"]["custom_forgot_multiplier"] is not None
                        else current.get("custom_forgot_multiplier", 0.45)
                    ),
                    custom_minimum_interval_hours=(
                        updates["review_mode"]["custom_minimum_interval_hours"]
                        if updates["review_mode"]["custom_minimum_interval_hours"] is not None
                        else current.get("custom_minimum_interval_hours", 6)
                    ),
                    custom_maximum_interval_hours=(
                        updates["review_mode"]["custom_maximum_interval_hours"]
                        if updates["review_mode"]["custom_maximum_interval_hours"] is not None
                        else current.get("custom_maximum_interval_hours", 1440)
                    ),
                    updated_at=now_epoch,
                )
                config["review_mode"] = {
                    "mode": mode.mode,
                    "custom_initial_interval_hours": mode.custom_initial_interval_hours,
                    "custom_remembered_multiplier": mode.custom_remembered_multiplier,
                    "custom_forgot_multiplier": mode.custom_forgot_multiplier,
                    "custom_minimum_interval_hours": mode.custom_minimum_interval_hours,
                    "custom_maximum_interval_hours": mode.custom_maximum_interval_hours,
                    "updated_at": mode.updated_at,
                }

            if "vocab_ui" in updates:
                vocab_ui = VocabUIConfig(
                    active_notebook_id=updates["vocab_ui"]["active_notebook_id"],
                    updated_at=now_epoch,
                )
                config["vocab_ui"] = {
                    "active_notebook_id": vocab_ui.active_notebook_id,
                    "updated_at": vocab_ui.updated_at,
                }

            record["config"] = config
            users[args.uid] = record
            return config

        cfg = _mutate_users(dd, mutate)
        state["config"] = cfg
        return {"config": cfg}

    def verify_fn() -> dict[str, Any]:
        users = load_users_from(users_file(dd), _passthrough_normalize)
        record = users.get(args.uid, {}) if isinstance(users.get(args.uid), dict) else {}
        config = record.get("config", {}) if isinstance(record.get("config"), dict) else {}
        mismatches: list[str] = []
        if "translation" in updates:
            tr = config.get("translation", {}) if isinstance(config.get("translation"), dict) else {}
            exp = state.get("config", {}).get("translation", {})
            if tr.get("source_lang") != exp.get("source_lang"):
                mismatches.append("translation.source_lang")
            if tr.get("target_lang") != exp.get("target_lang"):
                mismatches.append("translation.target_lang")
        if "review_clock" in updates:
            rc = config.get("review_clock", {}) if isinstance(config.get("review_clock"), dict) else {}
            exp = state.get("config", {}).get("review_clock", {})
            if rc.get("is_paused") != exp.get("is_paused"):
                mismatches.append("review_clock.is_paused")
            if rc.get("paused_at") != exp.get("paused_at"):
                mismatches.append("review_clock.paused_at")
        if "review_mode" in updates:
            rm = config.get("review_mode", {}) if isinstance(config.get("review_mode"), dict) else {}
            for key, value in state.get("config", {}).get("review_mode", {}).items():
                if key == "updated_at":
                    continue
                if rm.get(key) != value:
                    mismatches.append(f"review_mode.{key}")
        if "vocab_ui" in updates:
            vu = config.get("vocab_ui", {}) if isinstance(config.get("vocab_ui"), dict) else {}
            if vu.get("active_notebook_id") != resolved_nb_id:
                mismatches.append("vocab_ui.active_notebook_id")
        return {"ok": not mismatches, "mismatched": mismatches}

    return ctx.run(action="user-config-set", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)


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
    review_anchor = _parse_seed_datetime(spec.get("review_anchor"), "review_anchor")

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
                _parse_seed_datetime(rv.get("anchor"), f"cards[{i}].review.anchor")
            if "source" in c:
                _source_to_json(c.get("source"), f"cards[{i}].source")
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
        now = review_anchor or datetime.now(tz=UTC)
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
            if "source" in c:
                updates["source"] = _source_to_json(c.get("source"), "cards[].source")
            rv = c.get("review")
            if isinstance(rv, dict) and rv.get("state"):
                review_now = _parse_seed_datetime(rv.get("anchor"), "cards[].review.anchor") or now
                updates.update(_review_fields(rv["state"], rv.get("interval"), review_now))
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
                               confidence=float(lk["confidence"]), reason=lk["reason"], source="ops")
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
    graph_files = [n for n in names if n.endswith(".json") and f"/{_USER_BACKUP_META_DIR}/" not in n]
    has_record_snapshot = f"{args.uid}/{_USER_BACKUP_META_DIR}/{_USER_BACKUP_RECORD}" in names
    plan = {"restore_from": str(backup_path), "target_dir": str(ctx.user_dir),
            "available_backups": len(backups), "total_members": len(names),
            "db_files": len(db_files), "graph_files": len(graph_files),
            "has_record_snapshot": has_record_snapshot,
            "sample_members": names[:10]}

    def apply_fn() -> dict[str, Any]:
        # EditContext 已在此之前備份了當前 user_dir(若存在),所以即使還原錯版本
        # 也能再 restore 回來。先清掉現狀再解壓,避免新舊檔殘留混雜。
        if ctx.user_dir.exists():
            shutil.rmtree(ctx.user_dir)
        with tarfile.open(backup_path) as tar:
            record, email_index = _extract_user_backup_members(tar, args.uid, ctx.user_dir.parent)
        _restore_user_record_snapshot(dd, args.uid, record=record, email_index=email_index)
        return {"restored_from": str(backup_path), "restored_users_record": record is not None}

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


# ── clone-demo ─────────────────────────────────────────────
#
# 從一個高品質真帳號 byte-clone 整個 vocab 層(cards/notebooks/graph/embeddings/
# candidates)到目標 demo 帳號,再由 cards.db 的複習聚合合成 review_events.db。
# 走 store 級重放會丟 embeddings 並重算 graph;檔案級 clone 才是高保真。identity
# (users.json,在 data_dir 根、非 user_dir)結構上不被碰,故 demo 帳號保留自己的
# Google provider/email/subscription。

# vocab 層 SQLite(以 online backup API 複製,WAL-safe;不抓 -wal/-shm/.bak)。
# daily_review_stats.db 目前無 producer/consumer(heatmap 走合成的 review_events),
# 但生產 user_dir 實存此檔;為高保真一併複製(.exists() guard,缺則跳過,零風險)。
_CLONE_SQLITE = ("cards.db", "notebooks.db", "daily_review_stats.db")
# vocab 層衍生檔(精確 glob,排除 .bak/.lock/.tmp)。
_CLONE_GLOBS = (
    "graph_*.json", "embeddings_*.npy", "embeddings_meta_*.json",
    "candidates_*.json", "card_ids_*.json", "blocked_*.json",
)
# 目標端「屬於 vocab 層」的判定:clone 前清空,避免殘留舊 notebook 的孤兒
# graph/embeddings 與 -wal/-shm/.lock。review_events.db 一併清(由本次合成重建)。
_VOCAB_DB_STEMS = ("cards.db", "notebooks.db", "daily_review_stats.db", "review_events.db")
_VOCAB_PREFIXES = ("graph_", "embeddings_", "candidates_", "card_ids_", "blocked_")
_CLONE_TMP_SUFFIX = ".clone-tmp"


def _is_vocab_file(name: str) -> bool:
    """目標端某檔是否屬 clone 會接管的 vocab 層(含其 -wal/-shm/.lock/.bak 旁檔)。"""
    if name.endswith(_CLONE_TMP_SUFFIX):
        return False
    for stem in _VOCAB_DB_STEMS:
        if name == stem or name.startswith(stem + "-") or name.startswith(stem + "."):
            return True
    return any(name.startswith(p) for p in _VOCAB_PREFIXES)


def _sqlite_online_backup(src: Path, dst: Path) -> None:
    """以 SQLite online backup API 複製(WAL-safe,產出乾淨單檔,毋須 -wal/-shm)。

    backup 持有來源讀交易快照:即使來源正被 app 寫入也得一致快照,**不** checkpoint、
    **不**改 main db / -wal。唯一可能的副作用:來源 -shm 不存在且 -wal 有資料時,
    開 mode=ro 會重建一個 -shm sidecar(可再生、無害),故「source 唯讀」指邏輯資料不變。
    """
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def _clone_source_files(src_dir: Path) -> tuple[list[Path], list[Path]]:
    """回傳 (要 backup 的 SQLite 檔, 要直接複製的衍生檔)。"""
    sqlite_files = [src_dir / n for n in _CLONE_SQLITE if (src_dir / n).exists()]
    others: list[Path] = []
    for pat in _CLONE_GLOBS:
        others.extend(p for p in sorted(src_dir.glob(pat)) if p.is_file())
    return sqlite_files, others


def _parse_db_dt(raw: Any) -> datetime | None:
    """解析 cards.db 的 timestamp(naive 'YYYY-MM-DD HH:MM:SS.ffffff' 視為 UTC)。"""
    if not raw:
        return None
    s = str(raw).strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _read_card_review_states(cards_db: Path) -> list[CardReviewState]:
    """讀有複習紀錄的卡(含已刪 —— 過去複習仍是真實 heatmap 歷史)。"""
    if not cards_db.exists():
        return []
    conn = sqlite3.connect(f"file:{cards_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, content, notebook_id, review_count, lapse_count, review_streak, "
            "last_review_feedback, last_reviewed_at, created_at, review_interval_hours "
            "FROM card WHERE review_count > 0 AND last_reviewed_at IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    states: list[CardReviewState] = []
    for r in rows:
        last = _parse_db_dt(r["last_reviewed_at"])
        if last is None:
            continue
        created = _parse_db_dt(r["created_at"]) or last
        fb = r["last_review_feedback"]
        states.append(CardReviewState(
            card_id=r["id"],
            content=r["content"],
            notebook_id=r["notebook_id"] or "default",
            review_count=int(r["review_count"] or 0),
            lapse_count=int(r["lapse_count"] or 0),
            review_streak=int(r["review_streak"] or 0),
            last_review_feedback=int(fb) if fb is not None else -1,
            last_reviewed_at=last,
            created_at=created,
            review_interval_hours=float(r["review_interval_hours"] or 12.0),
        ))
    return states


def _count_active_cards(cards_db: Path) -> int:
    if not cards_db.exists():
        return 0
    conn = sqlite3.connect(f"file:{cards_db}?mode=ro", uri=True)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM card WHERE is_deleted = 0").fetchone()[0])
    finally:
        conn.close()


def _count_graph_links(user_dir: Path) -> int:
    """所有 graph_*.json 的 active link 總數。"""
    total = 0
    for p in sorted(user_dir.glob("graph_*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, list):
            total += sum(1 for lk in data if isinstance(lk, dict)
                         and lk.get("status", "active") == "active")
    return total


def _count_review_events(events_db: Path) -> int:
    if not events_db.exists():
        return 0
    store = ReviewEventStore(events_db)
    try:
        return len(store.all())
    finally:
        store.close()


def _clone_source_fingerprint(src_dir: Path) -> str:
    """對 clone-demo 實際複製的 vocab 層做穩定指紋，讓 scenario 可 pin 來源狀態。"""
    sqlite_files, other_files = _clone_source_files(src_dir)
    digest = hashlib.sha256()
    for path in [*sqlite_files, *other_files]:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                digest.update(chunk)
    return digest.hexdigest()


def cmd_clone_demo(args: argparse.Namespace) -> int:
    """高保真複製來源帳號 vocab 層到目標 demo 帳號 + 合成 review history。"""
    dd = data_dir()
    src_uid = args.source_uid
    assert_safe_uid(src_uid)                       # '../evil' 類在此 fail-loud
    src_dir = user_dir_for(dd, src_uid)
    if not src_dir.exists():
        raise EditError(f"source user not found: {src_uid}(在 {dd}/users/ 下無此目錄)")
    if not (src_dir / "cards.db").exists():
        raise EditError(f"source {src_uid} 無 cards.db,無詞庫可複製")

    # EditContext uid=target:寫前自動備份 target user_dir、要求 target 已存在、audit。
    ctx = EditContext(data_dir=dd, uid=args.target_uid, commit=args.commit, json_mode=args.json)
    if src_dir.resolve() == ctx.user_dir.resolve():
        raise EditError("source 與 target 不可為同一帳號")

    states = _read_card_review_states(src_dir / "cards.db")
    sqlite_files, other_files = _clone_source_files(src_dir)
    source_fingerprint = _clone_source_fingerprint(src_dir)
    if args.expect_source_fingerprint and args.expect_source_fingerprint != source_fingerprint:
        raise EditError(
            f"source fingerprint mismatch: expected {args.expect_source_fingerprint}, "
            f"got {source_fingerprint}"
        )
    source_links = _count_graph_links(src_dir)
    plan = {
        "source_uid": src_uid,
        "target_uid": args.target_uid,
        "source_fingerprint": source_fingerprint,
        "source_active_cards": _count_active_cards(src_dir / "cards.db"),
        "source_links": source_links,
        "synthesized_events": sum(s.review_count for s in states),
        "files_to_copy": [p.name for p in sqlite_files] + [p.name for p in other_files],
        "target_active_cards_before": _count_active_cards(ctx.user_dir / "cards.db"),
        "note": "identity(users.json)不變更;目標既有 vocab 層將被覆蓋",
    }

    def apply_fn() -> dict[str, Any]:
        tgt = ctx.user_dir
        # 1. 先把來源檔複製到 .clone-tmp(全成功才換入,降半寫風險;EditContext 另有 tar 兜底)。
        staged: list[tuple[Path, Path]] = []
        for sp in sqlite_files:
            tp = tgt / (sp.name + _CLONE_TMP_SUFFIX)
            _sqlite_online_backup(sp, tp)
            staged.append((tgt / sp.name, tp))
        for sp in other_files:
            tp = tgt / (sp.name + _CLONE_TMP_SUFFIX)
            shutil.copy2(sp, tp)
            staged.append((tgt / sp.name, tp))
        # 2. 清掉目標端舊 vocab 層(孤兒 graph/embeddings、-wal/-shm、舊 review_events)。
        removed = sorted(
            p.name for p in tgt.iterdir() if p.is_file() and _is_vocab_file(p.name)
        )
        for p in tgt.iterdir():
            if p.is_file() and _is_vocab_file(p.name):
                p.unlink()
        # 3. 暫存換入(換入前清 final 的 -wal/-shm,確保 SQLite 一致)。
        for final_path, tmp_path in staged:
            for suffix in ("-wal", "-shm"):
                (final_path.parent / (final_path.name + suffix)).unlink(missing_ok=True)
            tmp_path.replace(final_path)
        # 4. 由複製後的 cards.db 合成 review events 寫入目標 review_events.db。
        events = synthesize_many(_read_card_review_states(tgt / "cards.db"))
        events_written = 0
        if events:
            store = ReviewEventStore(tgt / "review_events.db")
            try:
                events_written = store.insert_many(events)["inserted"]
            finally:
                store.close()
        return {
            "cloned_sqlite": [p.name for p in sqlite_files],
            "cloned_files": [p.name for p in other_files],
            "removed_target_files": removed,
            "review_events_written": events_written,
            "source_fingerprint": source_fingerprint,
        }

    def verify_fn() -> dict[str, Any]:
        tgt = ctx.user_dir
        active = _count_active_cards(tgt / "cards.db")
        events = _count_review_events(tgt / "review_events.db")
        links = _count_graph_links(tgt)
        # 檔案完整性:衍生檔(copy2 精確複製)逐一比對來源大小,抓 truncated;SQLite 經
        # backup API 重排頁面大小會變,只驗存在且非空。補上 count-only verify 的盲點:
        # 一個 present-but-truncated 的 .npy 不會被卡數/連結數揪出。
        files_ok = all(
            (tgt / sp.name).exists() and (tgt / sp.name).stat().st_size == sp.stat().st_size
            for sp in other_files
        ) and all(
            (tgt / sp.name).exists() and (tgt / sp.name).stat().st_size > 0
            for sp in sqlite_files
        )
        ok = (
            active == plan["source_active_cards"]
            and events == plan["synthesized_events"]
            and links == plan["source_links"]
            and files_ok
        )
        return {
            "ok": ok,
            "target_active_cards": active,
            "review_events": events,
            "links": links,
            "files_ok": files_ok,
        }

    return ctx.run(action="clone-demo", plan=plan, apply_fn=apply_fn, verify_fn=verify_fn)


def _list_world_backups(dd: Path) -> list[dict[str, Any]]:
    root = world_backup_root(dd)
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.tar.gz"), reverse=True):
        st = p.stat()
        out.append({
            "path": str(p),
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
        })
    return out


def cmd_world_snapshot(args: argparse.Namespace) -> int:
    dd = data_dir()
    members = [p.name for p in _world_members(dd)]
    plan = {
        "label": args.label,
        "members": members,
        "member_count": len(members),
        "backup_root": str(world_backup_root(dd)),
    }
    if not args.commit:
        emit(
            {
                "mode": "dry-run",
                "action": "world-snapshot",
                "plan": plan,
                "committed": False,
                "hint": "加 --commit 才會真正建立 world snapshot",
            },
            json_mode=args.json,
        )
        return 0
    backup = backup_world(dd, label=args.label)
    emit(
        {
            "mode": "commit",
            "action": "world-snapshot",
            "plan": plan,
            "result": {"snapshot": str(backup)},
            "committed": True,
        },
        json_mode=args.json,
    )
    return 0


def cmd_world_restore(args: argparse.Namespace) -> int:
    dd = data_dir()
    snapshots = _list_world_backups(dd)
    if args.snapshot:
        snapshot_path = Path(args.snapshot)
        if not snapshot_path.exists():
            raise EditError(f"指定的 world snapshot 不存在: {snapshot_path}")
    else:
        if not snapshots:
            raise EditError("無 world snapshot 可還原")
        snapshot_path = Path(snapshots[0]["path"])

    with tarfile.open(snapshot_path) as tar:
        names = tar.getnames()
    top_dirs = {n.split("/")[0] for n in names if n and not n.startswith("/")}
    if top_dirs != {_WORLD_BACKUP_ROOT}:
        raise EditError(
            f"world snapshot root 不符: top={sorted(top_dirs)}, 預期僅 {{{_WORLD_BACKUP_ROOT!r}}}"
        )
    plan = {
        "restore_from": str(snapshot_path),
        "target_data_dir": str(dd),
        "available_snapshots": len(snapshots),
        "total_members": len(names),
    }
    if not args.commit:
        emit(
            {
                "mode": "dry-run",
                "action": "world-restore",
                "plan": plan,
                "committed": False,
                "hint": "加 --commit 才會真正覆蓋整個 data_dir world",
            },
            json_mode=args.json,
        )
        return 0

    pre_restore = backup_world(dd, label="pre-world-restore")
    with tempfile.TemporaryDirectory(prefix="kg-world-restore-") as tmp:
        tmp_root = Path(tmp)
        with tarfile.open(snapshot_path) as tar:
            tar.extractall(tmp_root, filter="data")
        restored = _replace_world_from_snapshot(dd, tmp_root / _WORLD_BACKUP_ROOT)
    emit(
        {
            "mode": "commit",
            "action": "world-restore",
            "plan": plan,
            "result": {
                "restored_from": str(snapshot_path),
                "pre_restore_backup": str(pre_restore),
                "restored_members": restored,
            },
            "verified": {"ok": users_file(dd).exists() and (dd / "users").exists()},
            "committed": True,
        },
        json_mode=args.json,
    )
    return 0


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

    p = sub.add_parser("user-config-set", parents=[jp, cp],
                       help="更新 user config(translation/review clock/mode/vocab UI)")
    p.add_argument("uid")
    p.add_argument("--translation-source")
    p.add_argument("--translation-target")
    p.add_argument("--review-clock", choices=["paused", "running"])
    p.add_argument("--paused-at", help="ISO datetime;僅搭配 --review-clock paused")
    p.add_argument("--review-mode", choices=["relaxed", "intensive", "custom"])
    p.add_argument("--custom-initial-interval-hours", type=float)
    p.add_argument("--custom-remembered-multiplier", type=float)
    p.add_argument("--custom-forgot-multiplier", type=float)
    p.add_argument("--custom-minimum-interval-hours", type=float)
    p.add_argument("--custom-maximum-interval-hours", type=float)
    p.add_argument("--active-notebook", help="notebook id 或 name")
    p.set_defaults(func=cmd_user_config_set)

    p = sub.add_parser("link-add", parents=[jp, cp], help="連結兩張卡(知識圖譜)")
    p.add_argument("uid")
    p.add_argument("from_ref", metavar="from", help="來源 card id 或 content")
    p.add_argument("to_ref", metavar="to", help="目標 card id 或 content")
    p.add_argument("--kind", required=True, choices=["contrasts_with", "shares_usage"])
    p.add_argument("--confidence", type=float, required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--notebook", default="default")
    p.add_argument("--if-exists", choices=["keep", "update"], default="keep",
                   help="既有 pair 存在時：keep=維持既有值(預設)；update=改寫 confidence/kind/reason")
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

    p = sub.add_parser("clone-demo", parents=[jp, cp],
                       help="高保真複製來源帳號 vocab 層到目標 demo 帳號 + 合成 review history")
    p.add_argument("source_uid", help="來源帳號 uid(讀取,不變更)")
    p.add_argument("target_uid", help="目標 demo 帳號 uid(覆蓋 vocab 層;identity 不動)")
    p.add_argument("--expect-source-fingerprint",
                   help="要求來源 vocab 層指紋相符，避免來源漂移導致 clone 結果改變")
    p.set_defaults(func=cmd_clone_demo)

    p = sub.add_parser("world-snapshot", parents=[jp, cp],
                       help="建立整個 data_dir world snapshot（users.json + users/* + 根目錄 DB）")
    p.add_argument("--label", default="world")
    p.set_defaults(func=cmd_world_snapshot)

    p = sub.add_parser("world-restore", parents=[jp, cp],
                       help="從 world snapshot 還原整個 data_dir")
    p.add_argument("--snapshot", help="指定 snapshot tar.gz（預設取最新）")
    p.set_defaults(func=cmd_world_restore)

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
    p.add_argument("--sort-order", type=int)
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
