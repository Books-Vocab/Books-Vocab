"""ops_world_export.py — 帳號 vocab 層 → ops_edit seed 相容 spec 的唯讀導出。

`ops_cli.py world-export <uid>` 的實作核心（行銷帳號系統可復現性地基）。與
`ops_world_projection`（state-diff 投影，**刻意只投影子集欄位**）不同，本模組導出
seed 可**無損重放**的全欄位：

* notebooks — name / color / cover_pattern / sort_order / is_default（排除 is_deleted 與 is_staged 複製中暫存本）
* cards — content / pos / meaning / examples / collocations / note / difficulty /
  mode / root_form / inflections / notebook(name 參照) / is_archived /
  source(VocabSource JSON，omit-if-null)
  + review 計數器（review_count / review_streak / lapse_count /
  review_interval_hours / next_review_at / last_reviewed_at / last_review_feedback）
* links — from / to（card content 參照）/ kind / confidence / reason / notebook

欄位取捨不是散文紀律：`EXPORTED_CARD_COLUMNS` / `EXPORT_IGNORED_CARD_COLUMNS`
（notebook 同名兩式）把「哪欄有導、哪欄刻意不導及其理由」寫成可斷言集合，由
`tests/test_ops_world_export.py::TestFieldSymmetry` 對 Card/Notebook model 守恆
——**給 model 加欄位而沒在那裡表態就會紅**（IMP-0016）。

唯讀紀律：SQLite 一律 `connect_ro`（mode=ro URI），graph 直讀 `graph_*.json`；
**不** import 任何開檔即寫的 store（`NotebookStore.__init__` 會 create_all DDL）
或 log 單例。

確定式：排序不依賴 created_at / 隨機 id（seed 重放到新沙盒後再 export 仍相等）——
notebooks 按 (sort_order, name)、cards 按 (notebook name, content)、links 按
(notebook name, from, to, kind)；datetime 一律正規化成 aware UTC isoformat，
故同一世界重跑 byte-stable、roundtrip 後 payload 相等。

不可重放的資料（孤兒卡的 notebook 已刪 / link 端點已刪）**不進 payload**，以
warning 回報 —— stdout 維持純 seed spec JSON。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ops_edit_shared import user_dir_for
from .ops_shared import connect_ro, data_dir

SEED_SPEC_SCHEMA = "kg.seed_spec.v1"

# seed 認得的 link kind（與 LinkKind 對齊；不 import graph 模組，避免拉重依賴）。
_LINK_KINDS = ("contrasts_with", "shares_usage")


class WorldExportError(RuntimeError):
    """export 無法產出 seed-replayable spec 時 fail-loud 的錯誤。"""


def _norm_dt(raw: Any) -> str | None:
    """DB datetime（naive 'YYYY-MM-DD HH:MM:SS.ffffff' 視為 UTC / 帶 offset）→ UTC isoformat。

    寫面可能以 naive（SQLModel 預設）或 aware（seed 直寫 tz-aware）落盤；export
    統一正規化，roundtrip 兩側才會 byte 相等。
    """
    if raw in (None, ""):
        return None
    s = str(raw).strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise WorldExportError(f"無法解析 datetime:{raw!r}") from exc
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.isoformat()


def _json_list(raw: Any) -> list[Any]:
    """DB 的 JSON 欄位（examples/collocations/inflections）→ list；NULL → []。"""
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        return raw
    try:
        val = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return val if isinstance(val, list) else []


def _ro_rows(db_path: Path, sql: str) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    conn = connect_ro(db_path)
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        conn.close()


def _ro_has_column(db_path: Path, table: str, column: str) -> bool:
    """Whether ``table.column`` exists (read-only PRAGMA). Lets the raw notebook
    read tolerate a legacy DB predating the ``is_staged`` migration — a filter on
    a missing column would be a parse error, not a no-op."""
    if not db_path.exists():
        return False
    conn = connect_ro(db_path)
    try:
        return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))
    finally:
        conn.close()


# ── 導出欄位分類（IMP-0016）────────────────────────────────────────
#
# 下面兩對常數是「哪個 DB 欄位有沒有導出」的唯一可斷言來源，就放在兩個 entry
# builder 正上方 —— 改 emitter 的人一定會看見它們。
#
# 為什麼需要：本檔的 roundtrip 契約（seed→export→seed→export 兩份相等）是個
# **自證迴圈**，兩份 export 都出自同一個手寫 dict。export 從不吐出的欄位，
# roundtrip 永遠不會想念 —— 給 Card/Notebook 加一欄而忘了在此表態，資料靜默
# 消失而測試全綠。這四個常數把「表態」變成強制動作。
#
# **禁止**從 SQLModel / PRAGMA 反射產生這些集合：那會讓宣告恆等於現實，
# lint 淪為 tautology，等於沒有防線。必須手寫，讓新增欄位卡在紅燈上。
#
# 由 `tests/test_ops_world_export.py::TestFieldSymmetry` 兩面守恆：
#   1. 對 MODEL：EXPORTED | IGNORED 恰等於 `Card` / `Notebook` 的欄位集。
#   2. 對 EMITTER：EXPORTED 的每條 payload 路徑真的出現在 export 輸出裡，
#      且 export 不吐出未宣告的鍵。
#
# EXPORTED_* 的值是該欄位在 payload 裡的路徑（tuple，長度 1 = 頂層鍵，
# 長度 2 = 單層巢狀）；IGNORED 的值是**不導的理由**，空字串不被接受。

EXPORTED_NOTEBOOK_COLUMNS: dict[str, tuple[str, ...]] = {
    "name": ("name",),
    "color": ("color",),
    "cover_pattern": ("cover_pattern",),
    "sort_order": ("sort_order",),
    "is_default": ("is_default",),
    # omit-if-null（僅 Phase 2 copy 蓋章的本才有）。
    "source_shared_deck_id": ("source_shared_deck_id",),
    "source_version": ("source_version",),
}

EXPORT_IGNORED_NOTEBOOK_COLUMNS: dict[str, str] = {
    "id": "內部 join key；payload 一律以 name 參照",
    "created_at": "store 自動戳，跨沙盒重放必變，導出會破 byte-equal",
    "updated_at": "store 自動戳，跨沙盒重放必變，導出會破 byte-equal",
    "is_deleted": "查詢過濾條件，非可重放值（軟刪本不進 payload）",
    "is_staged": "複製中暫存本的屏障；staged 本整筆不導（見 _export_notebooks）",
}

EXPORTED_CARD_COLUMNS: dict[str, tuple[str, ...]] = {
    "content": ("content",),
    "pos": ("pos",),
    "meaning": ("meaning",),
    "examples": ("examples",),
    "collocations": ("collocations",),
    "note": ("note",),
    "difficulty": ("difficulty",),
    "mode": ("mode",),
    "root_form": ("root_form",),
    "inflections": ("inflections",),
    # notebook_id 以 notebook name 表達（id 跨沙盒不穩定）。
    "notebook_id": ("notebook",),
    "is_archived": ("is_archived",),
    # VocabSource JSON，omit-if-null。
    "source": ("source",),
    # review 計數器收在巢狀 block。
    "review_interval_hours": ("review", "review_interval_hours"),
    "next_review_at": ("review", "next_review_at"),
    "last_reviewed_at": ("review", "last_reviewed_at"),
    "review_count": ("review", "review_count"),
    "lapse_count": ("review", "lapse_count"),
    "review_streak": ("review", "review_streak"),
    "last_review_feedback": ("review", "last_review_feedback"),
    # omit-if-null（僅 Phase 2 copy 蓋章的卡才有）。
    "source_shared_card_guid": ("source_shared_card_guid",),
}

EXPORT_IGNORED_CARD_COLUMNS: dict[str, str] = {
    "id": "內部 join key；payload 一律以 content 參照",
    "created_at": "store 自動戳，跨沙盒重放必變，導出會破 byte-equal",
    "updated_at": "store 自動戳，跨沙盒重放必變，導出會破 byte-equal",
    "is_deleted": "查詢過濾條件，非可重放值（軟刪卡不進 payload）",
    "content_nfc_lower": "content 的衍生索引，由寫面自動維護",
    # ── 以下 5 欄：seed 今日沒有攝入面 ──────────────────────────────
    # 列在這裡＝**明示承認 snapshot/restore 會丟掉它們**，不是宣稱無害。
    # §1.1 欄位對稱要求「export 吐出的每個欄位 seed 都要吃得進去」，硬導會讓
    # export A 吐鍵 → seed B 忽略 → export B 缺鍵 → byte-equal fixpoint 破。
    # 要真正保住這幾欄，得先擴 seed 的攝入面（另一條 entry，非本條範圍）。
    "card_role": "seed 無攝入面；由 spec 重建的世界會回退 learning（已知有損）",
    "review_eligible": "seed 無攝入面；重建後回退 True（已知有損）",
    "reader_hidden": "seed 無攝入面；重建後回退 False —— 這是**使用者意圖**，"
                     "是這批裡最該優先補攝入面的一欄（已知有損）",
    "promotion_state": "轉卡 job 狀態機，pipeline 衍生態，非可重放值",
    "promoted_at": "轉卡 job 時戳，pipeline 衍生態，非可重放值",
}


def _export_notebooks(user_dir: Path) -> list[dict[str, Any]]:
    db_path = user_dir / "notebooks.db"
    # Exclude soft-deleted AND copy-in-progress (staged) notebooks. is_staged is
    # a later migration, so filter on it only when the column is present (a
    # legacy DB with no staged rows is correct under is_deleted=0 alone).
    where = "is_deleted = 0"
    if _ro_has_column(db_path, "notebook", "is_staged"):
        where += " AND is_staged = 0"
    rows = _ro_rows(db_path, f"SELECT * FROM notebook WHERE {where}")
    rows.sort(key=lambda r: (int(r.get("sort_order") or 0), str(r.get("name") or "")))
    names = [str(r.get("name") or "") for r in rows]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        # 同名多本 → seed 的 name→id 映射無法區分，spec 不可重放；fail-loud。
        raise WorldExportError(f"active notebook name 重複，無法導出可重放 spec:{dupes}")
    return rows


def _notebook_entry(row: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": row.get("name"),
        "color": row.get("color"),
        "cover_pattern": row.get("cover_pattern"),
        "sort_order": int(row.get("sort_order") or 0),
        "is_default": bool(row.get("is_default")),
    }
    # Provenance is omit-if-null: specs predating shared decks carry no such
    # key, so emitting null would break the byte-equal roundtrip (§1.1). When
    # set (Phase 2 copy), export + seed stay field-symmetric.
    src_deck = row.get("source_shared_deck_id")
    if src_deck is not None:
        entry["source_shared_deck_id"] = src_deck
        entry["source_version"] = row.get("source_version")
    return entry


def _card_entry(row: dict[str, Any], notebook_name: str) -> dict[str, Any]:
    feedback = row.get("last_review_feedback")
    entry: dict[str, Any] = {
        "content": row.get("content"),
        "pos": row.get("pos"),
        "meaning": row.get("meaning") or "",
        "examples": _json_list(row.get("examples")),
        "collocations": _json_list(row.get("collocations")),
        "note": row.get("note"),
        "difficulty": row.get("difficulty"),
        "mode": row.get("mode") or "recognition",
        "root_form": row.get("root_form"),
        "inflections": _json_list(row.get("inflections")),
        "notebook": notebook_name,
        "is_archived": bool(row.get("is_archived")),
        "review": {
            "review_count": int(row.get("review_count") or 0),
            "review_streak": int(row.get("review_streak") or 0),
            "lapse_count": int(row.get("lapse_count") or 0),
            "review_interval_hours": float(row.get("review_interval_hours") or 12.0),
            "next_review_at": _norm_dt(row.get("next_review_at")),
            "last_reviewed_at": _norm_dt(row.get("last_reviewed_at")),
            "last_review_feedback": int(feedback) if feedback is not None else -1,
        },
    }
    # Provenance is omit-if-null, symmetric with _notebook_entry: cards predating
    # shared decks (or created organically) carry NULL, so emitting the key would
    # break the byte-equal roundtrip (§1.1). Set only by the Phase 2 copy path.
    src_guid = row.get("source_shared_card_guid")
    if src_guid is not None:
        entry["source_shared_card_guid"] = src_guid
    # source（VocabSource JSON）同樣 omit-if-null：無 source 的 spec 不得多出
    # null 鍵，否則既有世界的 byte-equal roundtrip 破功（§1.1）。json.loads 不加
    # try/except 是刻意的 —— 生產讀路徑 `vocab_shared.py` 解同一欄同樣無防護，
    # export 與之對稱，不新增一類失敗行為。
    raw_source = row.get("source")
    if raw_source:
        entry["source"] = json.loads(raw_source)
    return entry


def _export_links(
    user_dir: Path,
    nb_names: dict[str, str],
    card_content_by_id: dict[str, str],
    warnings: list[str],
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for path in sorted(user_dir.glob("graph_*.json")):
        nb_id = path.stem.removeprefix("graph_")
        nb_name = nb_names.get(nb_id)
        if nb_name is None:
            warnings.append(f"graph {path.name} 的 notebook 非 active，略過整檔")
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            warnings.append(f"graph {path.name} 讀取/解析失敗，略過整檔")
            continue
        entries = raw if isinstance(raw, list) else list(raw.values()) if isinstance(raw, dict) else []
        for link in entries:
            if not isinstance(link, dict) or link.get("status", "active") != "active":
                continue
            from_content = card_content_by_id.get(str(link.get("from_id")))
            to_content = card_content_by_id.get(str(link.get("to_id")))
            kind = link.get("kind")
            if from_content is None or to_content is None or kind not in _LINK_KINDS:
                warnings.append(
                    f"link {link.get('id')!r}({path.name})端點卡不在導出集或 kind 非法，略過"
                )
                continue
            links.append({
                "from": from_content,
                "to": to_content,
                "kind": kind,
                "confidence": float(link.get("confidence") or 0.0),
                "reason": link.get("reason") or "",
                "notebook": nb_name,
            })
    links.sort(key=lambda lk: (lk["notebook"], lk["from"], lk["to"], lk["kind"]))
    # app 語意：一對卡至多一條 active link（vocab_graph_ops.add_link 對既存 pair
    # 拋 ConflictError）。legacy graph 可能同 pair 存雙向多條——照導會產出
    # seed 無法完整重放的 spec（第二條被冪等吸收），違反 roundtrip 契約。
    # 確定式保留 sorted 首條，其餘 warning 略過。
    seen_pairs: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for lk in links:
        pair = (lk["notebook"], *sorted((lk["from"], lk["to"])))
        if pair in seen_pairs:
            warnings.append(
                f"同卡對多條 active link（{lk['from']} ↔ {lk['to']}，{lk['notebook']}）"
                f"，僅保留 sorted 首條（app 語意一對卡至多一條）"
            )
            continue
        seen_pairs.add(pair)
        deduped.append(lk)
    return deduped


def export_seed_spec(uid: str, *, data_root: Path | None = None) -> tuple[dict[str, Any], list[str]]:
    """把單一帳號 vocab 層 dump 成 `ops_edit.py seed` 相容 spec。

    回傳 (payload, warnings)。payload 確定式（見 module docstring），warnings 收
    不可重放而被略過的資料（呼叫端印 stderr，stdout 維持純 JSON）。
    """
    root = data_root or data_dir()
    user_dir = user_dir_for(root, uid)
    if not user_dir.exists():
        raise WorldExportError(f"user not found: {uid}（{root}/users/ 下無此目錄）")

    warnings: list[str] = []
    nb_rows = _export_notebooks(user_dir)
    nb_names = {str(r["id"]): str(r.get("name") or "") for r in nb_rows}

    card_rows = _ro_rows(user_dir / "cards.db", "SELECT * FROM card WHERE is_deleted = 0")
    cards: list[dict[str, Any]] = []
    card_content_by_id: dict[str, str] = {}
    for row in card_rows:
        nb_name = nb_names.get(str(row.get("notebook_id")))
        if nb_name is None:
            warnings.append(
                f"card {row.get('content')!r} 的 notebook {row.get('notebook_id')!r} 非 active（孤兒卡），略過"
            )
            continue
        if not str(row.get("meaning") or "").strip():
            # seed 預驗拒絕空 meaning；此卡不可重放，fail-loud 讓 operator 先修資料。
            raise WorldExportError(f"card {row.get('content')!r} meaning 空白，seed 不可重放；先修資料再導出")
        cards.append(_card_entry(row, nb_name))
        card_content_by_id[str(row.get("id"))] = str(row.get("content"))
    cards.sort(key=lambda c: (c["notebook"], c["content"]))

    links = _export_links(user_dir, nb_names, card_content_by_id, warnings)

    payload = {
        "schema": SEED_SPEC_SCHEMA,
        "notebooks": [_notebook_entry(r) for r in nb_rows],
        "cards": cards,
        "links": links,
    }
    return payload, warnings
