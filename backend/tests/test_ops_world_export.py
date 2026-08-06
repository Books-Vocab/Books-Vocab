"""world-export（帳號 → seed-spec 唯讀導出）+ seed review 計數器擴充的回歸護欄。

行銷帳號系統可復現性地基（Phase 1/6）的核心性質：
  seed(spec) → world-export → seed(新沙盒) → world-export ⇒ 兩份 export 語意相等。

全程 tmp_path 沙盒（KG_DATA_DIR 注入）、subprocess 跑真 CLI。斷言混用 export JSON、
--json stdout 與直接讀盤（cards.db / review_events.db），杜絕 false-green。
"""

import hashlib
import json
import sqlite3
from pathlib import Path

from ops_helpers import run_ops_cli as _cli
from ops_helpers import run_ops_edit as _edit

# ── helpers ────────────────────────────────────────────────────────


def _mk_user(dd: Path, uid: str = "demo") -> str:
    r = _edit(str(dd), "user-create", uid, "--commit", "--json")
    assert r.returncode == 0, r.stderr
    return uid


def _seed(dd: Path, uid: str, spec: dict, *extra: str):
    p = dd / f"spec-{hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:8]}.json"
    p.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return _edit(str(dd), "seed", uid, str(p), *extra)


def _export_raw(dd: Path, uid: str):
    return _cli(str(dd), "world-export", uid)


def _export(dd: Path, uid: str) -> dict:
    r = _export_raw(dd, uid)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _card_row(dd: Path, uid: str, content: str) -> dict | None:
    db = dd / "users" / uid / "cards.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM card WHERE content = ? AND is_deleted = 0", (content,)
        ).fetchone()
    except sqlite3.OperationalError:
        # 預驗拒絕於任何寫入前 → card 表可能根本沒建;等同「無此卡」。
        row = None
    conn.close()
    return dict(row) if row else None


def _review_event_rows(dd: Path, uid: str) -> list[dict]:
    db = dd / "users" / uid / "review_events.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT event_id, card_id, feedback FROM reviewevent").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# 覆蓋所有可導欄位的 rich spec（legacy review 形式 —— 既有消費者的形狀）。
_RICH_SPEC = {
    "review_anchor": "2026-06-11T00:00:00Z",
    "notebooks": [
        {"name": "Alpha", "color": "#112233", "cover_pattern": "waves", "sort_order": 2},
        {"name": "Beta", "color": "#445566", "cover_pattern": "dots", "sort_order": 1},
    ],
    "cards": [
        {
            "content": "meticulous", "meaning": "一絲不苟的", "pos": "adj.",
            "examples": ["Her **meticulous** notes."], "collocations": ["meticulous planning"],
            "note": "note-md", "difficulty": 4.5, "mode": "recognition",
            "notebook": "Alpha",
            "review": {"state": "reviewed", "interval": 72},
        },
        {
            "content": "wince", "meaning": "畏縮", "pos": "v.",
            "notebook": "Alpha",
            "review": {"state": "due", "interval": 24},
        },
        {"content": "plain", "meaning": "平凡的", "notebook": "Beta"},
        {"content": "defaulted", "meaning": "落在預設本"},
    ],
    "links": [
        {"from": "meticulous", "to": "wince", "kind": "shares_usage",
         "confidence": 0.8, "reason": "same chapter", "notebook": "Alpha"},
    ],
}


# ── world-export 基本面 ────────────────────────────────────────────


class TestWorldExport:
    def test_missing_user_is_error(self, tmp_path):
        r = _export_raw(tmp_path, "ghost")
        assert r.returncode != 0

    def test_export_shape_covers_all_seedable_fields(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _seed(tmp_path, uid, _RICH_SPEC, "--commit", "--json").returncode == 0
        out = _export(tmp_path, uid)

        assert out["schema"] == "kg.seed_spec.v1"
        nb_names = [n["name"] for n in out["notebooks"]]
        # 確定式排序：sort_order 優先（default=0 → Beta=1 → Alpha=2）。
        assert nb_names[-2:] == ["Beta", "Alpha"]
        default_nb = next(n for n in out["notebooks"] if n["is_default"])
        assert default_nb["sort_order"] == 0
        for n in out["notebooks"]:
            assert set(n) == {"name", "color", "cover_pattern", "sort_order", "is_default"}

        cards = {c["content"]: c for c in out["cards"]}
        met = cards["meticulous"]
        assert met["pos"] == "adj."
        assert met["examples"] == ["Her **meticulous** notes."]
        assert met["collocations"] == ["meticulous planning"]
        assert met["note"] == "note-md"
        assert met["difficulty"] == 4.5
        assert met["mode"] == "recognition"
        assert met["notebook"] == "Alpha"
        assert met["is_archived"] is False
        assert met["root_form"] is None
        assert met["inflections"] == []
        # review 計數器：legacy reviewed(interval=72) → count=2、feedback=1。
        rv = met["review"]
        assert set(rv) == {
            "review_count", "review_streak", "lapse_count", "review_interval_hours",
            "next_review_at", "last_reviewed_at", "last_review_feedback",
        }
        assert rv["review_count"] == 2
        assert rv["review_interval_hours"] == 72.0
        assert rv["last_reviewed_at"] == "2026-06-11T00:00:00+00:00"
        assert rv["last_review_feedback"] == 1
        # 從未複習的卡也帶完整計數器 block（lossless、確定形狀）。
        assert cards["plain"]["review"]["review_count"] == 0
        assert cards["plain"]["review"]["last_reviewed_at"] is None
        # 卡在 default 本 → 以 default 本的實際 name 參照。
        assert cards["defaulted"]["notebook"] == default_nb["name"]

        assert out["links"] == [{
            "from": "meticulous", "to": "wince", "kind": "shares_usage",
            "confidence": 0.8, "reason": "same chapter", "notebook": "Alpha",
        }]

    def test_export_is_byte_stable_and_readonly(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _seed(tmp_path, uid, _RICH_SPEC, "--commit", "--json").returncode == 0
        cards_db = tmp_path / "users" / uid / "cards.db"
        before = hashlib.sha256(cards_db.read_bytes()).hexdigest()
        r1 = _export_raw(tmp_path, uid)
        r2 = _export_raw(tmp_path, uid)
        assert r1.returncode == 0 and r2.returncode == 0
        assert r1.stdout == r2.stdout, "重跑 export 必須 byte-stable"
        assert hashlib.sha256(cards_db.read_bytes()).hexdigest() == before, \
            "world-export 是唯讀面，不可改動 cards.db"

    def test_export_excludes_deleted_cards(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _seed(tmp_path, uid, _RICH_SPEC, "--commit", "--json").returncode == 0
        assert _edit(str(tmp_path), "card-delete", uid, "plain", "--commit").returncode == 0
        out = _export(tmp_path, uid)
        assert "plain" not in {c["content"] for c in out["cards"]}

    def test_export_dedupes_multi_link_per_pair(self, tmp_path):
        """app 語意：一對卡至多一條 active link（add_link 對既存 pair 拋
        ConflictError）。legacy graph 資料可能同 pair 存雙向兩條——export 若
        照導，spec 重放時第二條被冪等吸收，roundtrip 破功。export 必須確定式
        保留 sorted 首條並 stderr warning。"""
        uid = _mk_user(tmp_path)
        assert _seed(tmp_path, uid, _RICH_SPEC, "--commit", "--json").returncode == 0
        user_dir = tmp_path / "users" / uid
        meticulous = _card_row(tmp_path, uid, "meticulous")
        wince = _card_row(tmp_path, uid, "wince")
        (graph_path,) = [
            p for p in user_dir.glob("graph_*.json")
            if json.loads(p.read_text(encoding="utf-8"))
        ]
        entries = json.loads(graph_path.read_text(encoding="utf-8"))
        assert isinstance(entries, list) and len(entries) == 1
        entries.append({
            **entries[0], "id": "legacy-reverse",
            "from_id": wince["id"], "to_id": meticulous["id"],
            "kind": "contrasts_with", "status": "active",
        })
        graph_path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")

        r = _export_raw(tmp_path, uid)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        pair_links = [
            l for l in out["links"]
            if {l["from"], l["to"]} == {"meticulous", "wince"}
        ]
        assert len(pair_links) == 1
        # 確定式：sorted (notebook, from, to, kind) 首條勝出
        assert (pair_links[0]["from"], pair_links[0]["kind"]) == ("meticulous", "shares_usage")
        assert "同卡對多條 active link" in r.stderr

    def test_export_out_flag_writes_file(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _seed(tmp_path, uid, _RICH_SPEC, "--commit", "--json").returncode == 0
        out_path = tmp_path / "export.json"
        r = _cli(str(tmp_path), "world-export", uid, "--out", str(out_path))
        assert r.returncode == 0, r.stderr
        assert json.loads(out_path.read_text(encoding="utf-8"))["schema"] == "kg.seed_spec.v1"


# ── seed review 計數器擴充 ─────────────────────────────────────────


class TestSeedReviewCounters:
    def _counters_spec(self, **overrides) -> dict:
        rv = {
            "review_count": 5, "review_streak": 3, "lapse_count": 1,
            "review_interval_hours": 48.0,
            "next_review_at": "2026-06-13T00:00:00+00:00",
            "last_reviewed_at": "2026-06-11T00:00:00+00:00",
            "last_review_feedback": 1,
            **overrides,
        }
        return {"cards": [{"content": "anchor", "meaning": "錨", "review": rv}]}

    def test_counters_land_on_disk_and_events_synthesized(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _seed(tmp_path, uid, self._counters_spec(), "--commit", "--json")
        assert r.returncode == 0, r.stderr
        row = _card_row(tmp_path, uid, "anchor")
        assert row["review_count"] == 5
        assert row["review_streak"] == 3
        assert row["lapse_count"] == 1
        assert row["review_interval_hours"] == 48.0
        assert row["last_review_feedback"] == 1
        assert row["last_reviewed_at"].startswith("2026-06-11")
        assert row["next_review_at"].startswith("2026-06-13")
        # 計數器 ⇒ 確定式合成逐筆 review events（餵 iOS heatmap/streak）。
        events = _review_event_rows(tmp_path, uid)
        assert len(events) == 5
        assert json.loads(r.stdout)["result"]["review_events_written"] == 5

    def test_counters_seed_is_idempotent(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _seed(tmp_path, uid, self._counters_spec(), "--commit", "--json").returncode == 0
        r2 = _seed(tmp_path, uid, self._counters_spec(), "--commit", "--json")
        assert r2.returncode == 0, r2.stderr
        # uuid5 確定式 event_id → 重跑經 store 去重，不增殖。
        assert len(_review_event_rows(tmp_path, uid)) == 5
        assert json.loads(r2.stdout)["result"]["review_events_written"] == 0

    def test_legacy_state_form_untouched(self, tmp_path):
        """既有 {state,interval} 消費者（ops/demo/demo_dataset.json）行為不變。"""
        uid = _mk_user(tmp_path)
        r = _seed(tmp_path, uid, {
            "review_anchor": "2026-06-11T00:00:00Z",
            "cards": [{"content": "w", "meaning": "m",
                       "review": {"state": "due", "interval": 24}}],
        }, "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert _card_row(tmp_path, uid, "w")["review_count"] == 1
        # legacy 形式不合成 review events（原行為）。
        assert _review_event_rows(tmp_path, uid) == []

    def test_rejects_mixed_state_and_counters(self, tmp_path):
        uid = _mk_user(tmp_path)
        spec = self._counters_spec()
        spec["cards"][0]["review"]["state"] = "reviewed"
        r = _seed(tmp_path, uid, spec, "--commit", "--json")
        assert r.returncode != 0
        assert _card_row(tmp_path, uid, "anchor") is None

    def test_rejects_counters_without_last_reviewed(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _seed(tmp_path, uid, {
            "cards": [{"content": "anchor", "meaning": "錨",
                       "review": {"review_count": 3}}],
        }, "--commit", "--json")
        assert r.returncode != 0
        assert _card_row(tmp_path, uid, "anchor") is None

    def test_rejects_unknown_counter_key(self, tmp_path):
        uid = _mk_user(tmp_path)
        spec = self._counters_spec(bogus_key=1)
        r = _seed(tmp_path, uid, spec, "--commit", "--json")
        assert r.returncode != 0
        assert _card_row(tmp_path, uid, "anchor") is None


# ── seed 新欄位（notebooks sort_order/is_default、cards root_form/inflections/is_archived） ──


class TestSeedFieldParity:
    def test_seed_applies_new_card_fields(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _seed(tmp_path, uid, {
            "cards": [{"content": "laid", "meaning": "放置(過去式)",
                       "root_form": "lay", "inflections": ["laid", "lays", "laying"],
                       "is_archived": True}],
        }, "--commit", "--json")
        assert r.returncode == 0, r.stderr
        row = _card_row(tmp_path, uid, "laid")
        assert row["root_form"] == "lay"
        assert json.loads(row["inflections"]) == ["laid", "lays", "laying"]
        assert row["is_archived"] == 1

    def test_seed_applies_notebook_sort_order_and_default_rename(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _seed(tmp_path, uid, {
            "notebooks": [
                {"name": "Renamed Default", "is_default": True, "sort_order": 0},
                {"name": "Second", "sort_order": 7},
            ],
        }, "--commit", "--json")
        assert r.returncode == 0, r.stderr
        conn = sqlite3.connect(str(tmp_path / "users" / uid / "notebooks.db"))
        conn.row_factory = sqlite3.Row
        rows = {r["name"]: dict(r) for r in conn.execute(
            "SELECT id, name, sort_order, is_default FROM notebook WHERE is_deleted = 0")}
        conn.close()
        # is_default: true → 映射到既存 default 本（改名，不增殖新本）。
        assert rows["Renamed Default"]["id"] == "default"
        assert rows["Second"]["sort_order"] == 7
        assert len(rows) == 2

    def test_rejects_two_defaults(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _seed(tmp_path, uid, {
            "notebooks": [{"name": "A", "is_default": True},
                          {"name": "B", "is_default": True}],
        }, "--commit", "--json")
        assert r.returncode != 0


# ── roundtrip 性質（DoD 核心） ─────────────────────────────────────


class TestRoundtrip:
    def test_seed_export_seed_export_is_fixpoint(self, tmp_path):
        dd_a = tmp_path / "a"
        dd_b = tmp_path / "b"
        dd_a.mkdir()
        dd_b.mkdir()
        uid_a = "world-a"
        uid_b = "world-b"
        _mk_user(dd_a, uid_a)
        _mk_user(dd_b, uid_b)

        # 世界 A：rich spec + 追加 archived / root_form 卡 + default 本卡。
        spec = json.loads(json.dumps(_RICH_SPEC))
        spec["cards"].append({
            "content": "laid", "meaning": "放置(過去式)", "root_form": "lay",
            "inflections": ["laid", "lays"], "is_archived": True, "notebook": "Beta",
        })
        assert _seed(dd_a, uid_a, spec, "--commit", "--json").returncode == 0

        r_a = _export_raw(dd_a, uid_a)
        assert r_a.returncode == 0, r_a.stderr
        export_a = json.loads(r_a.stdout)

        # export A 直接作為 seed spec 重放到全新沙盒 B。
        replay = dd_b / "replay.json"
        replay.write_text(r_a.stdout, encoding="utf-8")
        r_seed = _edit(str(dd_b), "seed", uid_b, str(replay), "--commit", "--json")
        assert r_seed.returncode == 0, r_seed.stdout + r_seed.stderr
        assert json.loads(r_seed.stdout)["verified"]["ok"] is True

        r_b = _export_raw(dd_b, uid_b)
        assert r_b.returncode == 0, r_b.stderr
        # 語意相等且（payload 無 uid/路徑）byte 相等。
        assert json.loads(r_b.stdout) == export_a
        assert r_b.stdout == r_a.stdout

        # review 計數器經 roundtrip 無損（含 due 卡的到期時間）。
        cards_b = {c["content"]: c for c in json.loads(r_b.stdout)["cards"]}
        assert cards_b["meticulous"]["review"]["review_count"] == 2
        assert cards_b["wince"]["review"]["next_review_at"] is not None
        # 世界 B 由計數器合成了逐筆 review events（A 是 legacy seed，無事件）。
        assert len(_review_event_rows(dd_b, uid_b)) == 3  # meticulous 2 + wince 1


# ── 欄位對稱守恆（IMP-0016） ───────────────────────────────────────
#
# 本檔其餘測試（含 TestRoundtrip 的 byte-equal fixpoint）都是**自證迴圈**：
# 不變量是 `export_a == export_b`，而兩份 export 都出自同一個手寫 `_card_entry`。
# 一個 export 從不吐出的欄位，是一個測試永遠不會想念的欄位 —— 新增 DB 欄位而
# 沒在 export 面表態時，roundtrip 依然 byte-equal 全綠，資料靜默消失。
#
# 下面這組測試把「權威」搬到 export 之外，串成兩條互不重疊的鏈：
#   MODEL（Card/Notebook SQLModel）→ 宣告（EXPORTED/IGNORED 常數）→ EMITTER（export stdout）
# 任何一段斷掉就紅。斷言的每個字串都由 export 以外的來源產生。


def _expected_payload_shape(declared: dict) -> tuple[set[str], dict[str, set[str]]]:
    """宣告的 payload 路徑 → (頂層鍵集, {巢狀 group: 子鍵集})。

    路徑深度只支援 1（頂層鍵）與 2（單層巢狀，如 review block）；出現更深的
    路徑代表 payload 形狀變了而這個 helper 沒跟上，直接 fail 而非默默略過。
    """
    top: set[str] = set()
    nested: dict[str, set[str]] = {}
    for col, path in declared.items():
        assert isinstance(path, tuple) and 1 <= len(path) <= 2, \
            f"{col} 的 payload 路徑深度未支援：{path!r}"
        top.add(path[0])
        if len(path) == 2:
            nested.setdefault(path[0], set()).add(path[1])
    return top, nested


# 每個「宣告有導出」的欄位都被填成非預設值的 spec —— omit-if-null 的欄位
# （source / source_shared_card_guid / notebook provenance）唯有如此才會現身，
# payload 才可能與宣告集完全對齊。
_MAX_SPEC = {
    "notebooks": [{
        "name": "Full", "color": "#abcdef", "cover_pattern": "grid", "sort_order": 3,
        "source_shared_deck_id": "deck-xyz", "source_version": 7,
    }],
    "cards": [{
        "content": "exhaustive", "meaning": "詳盡的", "pos": "adj.",
        "examples": ["An **exhaustive** list."], "collocations": ["exhaustive search"],
        "note": "note-md", "difficulty": 3.25, "mode": "production",
        "root_form": "exhaust", "inflections": ["exhaustive", "exhaustively"],
        "is_archived": True, "notebook": "Full",
        "source": {"type": "book", "title": "Demo Book", "chapter": "Chapter 1"},
        "source_shared_card_guid": "guid-abc",
        "review": {
            "review_count": 5, "review_streak": 3, "lapse_count": 1,
            "review_interval_hours": 48.0,
            "next_review_at": "2026-06-13T00:00:00+00:00",
            "last_reviewed_at": "2026-06-11T00:00:00+00:00",
            "last_review_feedback": 1,
        },
    }],
}


class TestFieldSymmetry:
    def test_card_columns_are_all_classified(self):
        """鏈的第一段：MODEL → 宣告。新增 Card 欄位而未表態即紅。

        權威是 `Card.__table__`（SQLModel 定義），不是 export 的輸出。
        """
        from kg.cards.model import Card
        from kg.ops_world_export import (
            EXPORT_IGNORED_CARD_COLUMNS,
            EXPORTED_CARD_COLUMNS,
        )

        model_cols = set(Card.__table__.columns.keys())
        exported = set(EXPORTED_CARD_COLUMNS)
        ignored = set(EXPORT_IGNORED_CARD_COLUMNS)
        assert exported & ignored == set(), \
            f"同時宣告導出與忽略：{sorted(exported & ignored)}"
        assert model_cols == exported | ignored, (
            f"未分類欄位={sorted(model_cols - (exported | ignored))} / "
            f"幽靈宣告={sorted((exported | ignored) - model_cols)}"
        )
        # 忽略理由不得空白 —— 沒人寫得出理由的欄位不該被靜默丟掉。
        assert all(str(v).strip() for v in EXPORT_IGNORED_CARD_COLUMNS.values())

    def test_notebook_columns_are_all_classified(self):
        """鏈的第一段（notebook 側）。"""
        from kg.notebook import Notebook
        from kg.ops_world_export import (
            EXPORT_IGNORED_NOTEBOOK_COLUMNS,
            EXPORTED_NOTEBOOK_COLUMNS,
        )

        model_cols = set(Notebook.__table__.columns.keys())
        exported = set(EXPORTED_NOTEBOOK_COLUMNS)
        ignored = set(EXPORT_IGNORED_NOTEBOOK_COLUMNS)
        assert exported & ignored == set(), \
            f"同時宣告導出與忽略：{sorted(exported & ignored)}"
        assert model_cols == exported | ignored, (
            f"未分類欄位={sorted(model_cols - (exported | ignored))} / "
            f"幽靈宣告={sorted((exported | ignored) - model_cols)}"
        )
        assert all(str(v).strip() for v in EXPORT_IGNORED_NOTEBOOK_COLUMNS.values())

    def test_model_columns_match_on_disk_schema(self, tmp_path):
        """把「MODEL 是權威」這個前提本身驗掉。

        上面兩條拿 SQLModel 當權威；這條確認真的落盤的 schema 與 model 一致
        （lazy-ALTER 遷移只加 model 裡有的欄位）。若哪天遷移加了 model 沒有的
        欄位，上面的守恆就會漏掉它 —— 這條會先紅。
        """
        from kg.cards.model import Card
        from kg.notebook import Notebook

        uid = _mk_user(tmp_path)
        assert _seed(tmp_path, uid, _MAX_SPEC, "--commit", "--json").returncode == 0
        for db_name, table, model in (
            ("cards.db", "card", Card),
            ("notebooks.db", "notebook", Notebook),
        ):
            conn = sqlite3.connect(str(tmp_path / "users" / uid / db_name))
            disk = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            conn.close()
            assert disk, f"{db_name} 未建 {table} 表，測試失去意義"
            assert disk == set(model.__table__.columns.keys()), (
                f"{table} 落盤 schema 與 model 不符："
                f"盤有 model 無={sorted(disk - set(model.__table__.columns.keys()))} / "
                f"model 有盤無={sorted(set(model.__table__.columns.keys()) - disk)}"
            )

    def test_declared_export_paths_match_payload(self, tmp_path):
        """鏈的第二段：宣告 → EMITTER。

        宣告「有導出」卻沒真的導（死宣告），或 export 吐出未宣告的鍵，都紅。
        少了這條，EXPORTED_* 只是註解：把新欄位塞進 EXPORTED 卻不改
        `_card_entry`，第一段測試照樣綠，資料照樣掉。
        """
        from kg.ops_world_export import (
            EXPORTED_CARD_COLUMNS,
            EXPORTED_NOTEBOOK_COLUMNS,
        )

        uid = _mk_user(tmp_path)
        assert _seed(tmp_path, uid, _MAX_SPEC, "--commit", "--json").returncode == 0
        out = _export(tmp_path, uid)

        card_top, card_nested = _expected_payload_shape(EXPORTED_CARD_COLUMNS)
        nb_top, nb_nested = _expected_payload_shape(EXPORTED_NOTEBOOK_COLUMNS)
        assert nb_nested == {}, "notebook payload 目前無巢狀 group"

        # 任何 entry 都不得吐出未宣告的鍵（omit-if-null 允許少，不允許多）。
        for c in out["cards"]:
            assert set(c) <= card_top, f"未宣告的 card 鍵：{sorted(set(c) - card_top)}"
        for n in out["notebooks"]:
            assert set(n) <= nb_top, f"未宣告的 notebook 鍵：{sorted(set(n) - nb_top)}"

        # 欄位填滿的那筆必須恰好吐出全部宣告鍵（沒有死宣告）。
        card = {c["content"]: c for c in out["cards"]}["exhaustive"]
        assert set(card) == card_top, \
            f"宣告有導但沒導={sorted(card_top - set(card))} / 多導={sorted(set(card) - card_top)}"
        for group, keys in card_nested.items():
            assert set(card[group]) == keys, \
                f"{group} block：缺={sorted(keys - set(card[group]))} / 多={sorted(set(card[group]) - keys)}"
        nb = {n["name"]: n for n in out["notebooks"]}["Full"]
        assert set(nb) == nb_top, \
            f"宣告有導但沒導={sorted(nb_top - set(nb))} / 多導={sorted(set(nb) - nb_top)}"

    def test_card_source_survives_roundtrip(self, tmp_path):
        """IMP-0016 已經在發生的那筆損失：reader 來源脈絡（VocabSource）。

        刻意不 import 任何新常數 —— 這條必須因**行為**而紅。最後一句直讀世界 B
        的 SQLite，不看 export 自己的回顯，杜絕自證。
        """
        src = {"type": "book", "title": "Demo Book", "chapter": "Chapter 1"}
        dd_a = tmp_path / "a"
        dd_b = tmp_path / "b"
        dd_a.mkdir()
        dd_b.mkdir()
        uid_a = _mk_user(dd_a, "src-a")
        uid_b = _mk_user(dd_b, "src-b")
        spec = {"cards": [{"content": "w", "meaning": "m", "source": src}]}
        assert _seed(dd_a, uid_a, spec, "--commit", "--json").returncode == 0
        assert _card_row(dd_a, uid_a, "w")["source"], "前提不成立：seed 沒把 source 寫進世界 A"

        r_a = _export_raw(dd_a, uid_a)
        assert r_a.returncode == 0, r_a.stderr
        card = {c["content"]: c for c in json.loads(r_a.stdout)["cards"]}["w"]
        assert "source" in card, "export 丟掉 cards[].source（IMP-0016 的靜默有損）"
        assert card["source"] == src

        replay = dd_b / "replay.json"
        replay.write_text(r_a.stdout, encoding="utf-8")
        assert _edit(str(dd_b), "seed", uid_b, str(replay), "--commit", "--json").returncode == 0
        r_b = _export_raw(dd_b, uid_b)
        assert r_b.returncode == 0, r_b.stderr
        assert r_b.stdout == r_a.stdout, "byte-equal fixpoint 破了"
        assert json.loads(_card_row(dd_b, uid_b, "w")["source"]) == src, \
            "重放後的世界 B 盤上沒有 source —— snapshot/restore 有損"

    def test_omit_if_null_keeps_sparse_cards_lean(self, tmp_path):
        """反向護欄：沒有 source 的卡不得多出 null 鍵。

        無條件 emit 會讓既有無 source 的 spec 多一個鍵，破 byte-equal roundtrip；
        這條把「omit-if-null」釘成契約而非巧合。
        """
        uid = _mk_user(tmp_path)
        assert _seed(tmp_path, uid, _RICH_SPEC, "--commit", "--json").returncode == 0
        out = _export(tmp_path, uid)
        for c in out["cards"]:
            assert "source" not in c, f"{c['content']} 不該有 source 鍵"
            assert "source_shared_card_guid" not in c
