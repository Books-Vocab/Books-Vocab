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
