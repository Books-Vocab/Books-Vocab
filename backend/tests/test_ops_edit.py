"""ops_edit.py 測試 — 第三輪 dogfooding（B 安全 / C 契約 / A 完備性）修復的回歸護欄。

全程 tmp_path 沙盒（KG_DATA_DIR 注入），subprocess 跑真 CLI，斷言混用 --json
stdout 與直接讀盤（cards.db / notebooks.db / graph_*.json），確保 verify 報的綠
與磁碟真實狀態一致 —— 正是本輪獵殺 false-green 的核心手法。
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ops_helpers import run_ops_cli as _cli
from ops_helpers import run_ops_edit as _edit

# ── 讀盤 helpers（繞過工具自身的 verify，看磁碟真相） ──────────────


def _user_dir(tmp_path: Path, uid: str) -> Path:
    return tmp_path / "users" / uid


def _card_rows(tmp_path: Path, uid: str) -> list[dict]:
    db = _user_dir(tmp_path, uid) / "cards.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, content, meaning, notebook_id, next_review_at, "
        "last_reviewed_at, review_interval_hours, review_count, "
        "last_review_feedback, source FROM card WHERE is_deleted = 0"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _card_by_content(tmp_path: Path, uid: str, content: str) -> dict | None:
    return next((r for r in _card_rows(tmp_path, uid) if r["content"] == content), None)


def _card_field(tmp_path: Path, uid: str, content: str, field: str):
    """讀單卡的 JSON 欄位(examples/collocations)或純值,繞 verify 看磁碟真相。"""
    db = _user_dir(tmp_path, uid) / "cards.db"
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        f"SELECT {field} FROM card WHERE content = ? AND is_deleted = 0", (content,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    val = row[0]
    if field in ("examples", "collocations", "inflections") and isinstance(val, str):
        return json.loads(val)
    return val


def _notebook_rows(tmp_path: Path, uid: str) -> list[dict]:
    db = _user_dir(tmp_path, uid) / "notebooks.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, name, sort_order FROM notebook WHERE is_deleted = 0"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _graph_links(tmp_path: Path, uid: str, notebook_id: str = "default") -> list[dict]:
    p = _user_dir(tmp_path, uid) / f"graph_{notebook_id}.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    return data if isinstance(data, list) else list(data.values())


def _mk_user(tmp_path: Path, uid: str = "demo") -> str:
    r = _edit(str(tmp_path), "user-create", uid, "--commit", "--json")
    assert r.returncode == 0, r.stderr
    return uid


def _mk_notebook(tmp_path: Path, uid: str, name: str) -> str:
    """建 notebook 回傳其 hex id（讀 --json result）。"""
    r = _edit(str(tmp_path), "notebook-create", uid, name, "--commit", "--json")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["result"]["notebook"]["id"]


# ── A HIGH-2 / MED-3 / LOW-3：--notebook name→id 解析（防孤兒卡） ──


class TestNotebookResolver:
    def test_card_add_resolves_notebook_name(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "Classic Literature")
        r = _edit(str(tmp_path), "card-add", uid, "wince", "--meaning", "畏縮",
                  "--notebook", "Classic Literature", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        card = _card_by_content(tmp_path, uid, "wince")
        # 關鍵：notebook_id 必須是 hex id，而非把 name 字串直存（孤兒卡）。
        assert card["notebook_id"] == nb_id
        assert card["notebook_id"] != "Classic Literature"

    def test_card_add_rejects_unknown_notebook(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _edit(str(tmp_path), "card-add", uid, "ghost", "--meaning", "鬼",
                  "--notebook", "Nonexistent", "--commit", "--json")
        assert r.returncode != 0
        assert "notebook" in (r.stdout + r.stderr).lower()
        assert _card_by_content(tmp_path, uid, "ghost") is None

    def test_card_add_default_still_works(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _edit(str(tmp_path), "card-add", uid, "plain", "--meaning", "平",
                  "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert _card_by_content(tmp_path, uid, "plain")["notebook_id"] == "default"

    def test_card_add_accepts_raw_id(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "ById")
        r = _edit(str(tmp_path), "card-add", uid, "byid", "--meaning", "m",
                  "--notebook", nb_id, "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert _card_by_content(tmp_path, uid, "byid")["notebook_id"] == nb_id

    def test_link_add_resolves_notebook_name(self, tmp_path):
        uid = _mk_user(tmp_path)
        _mk_notebook(tmp_path, uid, "Lit")
        for w, m in [("quill", "羽毛筆"), ("plush", "豪華的")]:
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", m,
                         "--notebook", "Lit", "--commit").returncode == 0
        r = _edit(str(tmp_path), "link-add", uid, "quill", "plush",
                  "--kind", "shares_usage", "--confidence", "0.8",
                  "--reason", "both literary", "--notebook", "Lit", "--commit", "--json")
        assert r.returncode == 0, r.stderr

    def test_card_import_resolves_notebook_name(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "Imported")
        csv = tmp_path / "cards.csv"
        csv.write_text("content,meaning\ndecorum,禮節\ndeft,靈巧的\n")
        r = _edit(str(tmp_path), "card-import", uid, str(csv),
                  "--notebook", "Imported", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert _card_by_content(tmp_path, uid, "decorum")["notebook_id"] == nb_id


# ── B1 / A HIGH-1：restore 安全 + 早期快照不誤判 ──────────────────


class TestRestoreSafety:
    def test_restore_rejects_foreign_backup(self, tmp_path):
        """指向他人 uid 的備份應在 rmtree 前被擋，victim 目錄完好。"""
        _mk_user(tmp_path, "victim")
        assert _edit(str(tmp_path), "card-add", "victim", "precious",
                     "--meaning", "珍貴", "--commit").returncode == 0
        _mk_user(tmp_path, "attacker")
        assert _edit(str(tmp_path), "card-add", "attacker", "evil",
                     "--meaning", "惡", "--commit").returncode == 0
        foreign = sorted((tmp_path / "_ops_backups").glob("attacker__*.tar.gz"))[-1]
        r = _edit(str(tmp_path), "restore", "victim", "--backup", str(foreign),
                  "--commit", "--json")
        assert r.returncode != 0
        # victim 的資料未被消滅。
        assert _card_by_content(tmp_path, "victim", "precious") is not None

    def test_restore_early_snapshot_ok(self, tmp_path):
        """還原到只含 notebooks.db 的早期快照應視為成功（非 cards.db 缺失=失敗）。"""
        uid = _mk_user(tmp_path)
        # 第一次 card-add 寫前會備份「當前 user_dir」= 只有 notebooks.db。
        assert _edit(str(tmp_path), "card-add", uid, "w1", "--meaning", "m",
                     "--commit").returncode == 0
        early = sorted((tmp_path / "_ops_backups").glob(f"{uid}__*.tar.gz"))[0]
        r = _edit(str(tmp_path), "restore", uid, "--backup", str(early),
                  "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["verified"]["ok"] is True

    def test_restore_restores_users_json_config_snapshot(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "Pinned")
        first = _edit(
            str(tmp_path), "user-config-set", uid,
            "--review-clock", "paused",
            "--active-notebook", "Pinned",
            "--commit", "--json",
        )
        assert first.returncode == 0, first.stderr
        second = _edit(
            str(tmp_path), "user-config-set", uid,
            "--review-clock", "running",
            "--commit", "--json",
        )
        assert second.returncode == 0, second.stderr
        latest = json.loads(_edit(str(tmp_path), "list-backups", uid, "--json").stdout)["backups"][0]["path"]
        restored = _edit(str(tmp_path), "restore", uid, "--backup", latest, "--commit", "--json")
        assert restored.returncode == 0, restored.stderr
        users = json.loads((tmp_path / "users.json").read_text())
        cfg = users[uid]["config"]
        assert cfg["review_clock"]["is_paused"] is True
        assert cfg["vocab_ui"]["active_notebook_id"] == nb_id


class TestWorldSnapshots:
    def test_world_snapshot_and_restore_roundtrip(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _edit(str(tmp_path), "card-add", uid, "baseline", "--meaning", "m", "--commit").returncode == 0
        snap = _edit(str(tmp_path), "world-snapshot", "--label", "baseline", "--commit", "--json")
        assert snap.returncode == 0, snap.stderr
        snapshot_path = json.loads(snap.stdout)["result"]["snapshot"]

        assert _edit(str(tmp_path), "card-add", uid, "after", "--meaning", "m", "--commit").returncode == 0
        assert _mk_user(tmp_path, "other") == "other"
        restore = _edit(str(tmp_path), "world-restore", "--snapshot", snapshot_path, "--commit", "--json")
        assert restore.returncode == 0, restore.stderr
        assert _card_by_content(tmp_path, uid, "baseline") is not None
        assert _card_by_content(tmp_path, uid, "after") is None
        assert not (tmp_path / "users" / "other").exists()


# ── B2：card-import / seed 寫入前預驗（原子性，杜絕半寫） ──────────


class TestImportAtomicity:
    def test_invalid_interval_no_partial_write(self, tmp_path):
        uid = _mk_user(tmp_path)
        csv = tmp_path / "bad.csv"
        csv.write_text(
            "content,meaning,review_state,review_interval\n"
            "good1,m1,due,12\n"
            "bad,m2,due,NOTANUMBER\n"
            "good2,m3,new,\n"
        )
        r = _edit(str(tmp_path), "card-import", uid, str(csv), "--commit", "--json")
        assert r.returncode != 0
        # 預驗應在任何寫入前攔截 → 0 卡落地。
        assert _card_rows(tmp_path, uid) == []


# ── B3 / B5 / A MED-1 / LOW-1 / C2 / C3 / MED-2 / MED-4：seed 加固 ─


class TestSeedValidation:
    def _seed(self, tmp_path, uid, spec, *extra):
        p = tmp_path / "spec.json"
        p.write_text(json.dumps(spec))
        return _edit(str(tmp_path), "seed", uid, str(p), *extra)

    def test_invalid_json_is_structured_error(self, tmp_path):
        uid = _mk_user(tmp_path)
        p = tmp_path / "notjson.txt"
        p.write_text("{ this is not json")
        r = _edit(str(tmp_path), "seed", uid, str(p), "--commit", "--json")
        assert r.returncode != 0
        # 必須是結構化 error JSON，而非 raw traceback。
        assert "error" in json.loads(r.stdout)

    def test_rejects_blank_meaning(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = self._seed(tmp_path, uid,
                       {"cards": [{"content": "orphan"}]}, "--commit", "--json")
        assert r.returncode != 0
        assert _card_rows(tmp_path, uid) == []

    def test_rejects_invalid_review_state(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = self._seed(tmp_path, uid,
                       {"cards": [{"content": "w", "meaning": "m",
                                   "review": {"state": "bogus"}}]},
                       "--commit", "--json")
        assert r.returncode != 0
        assert _card_rows(tmp_path, uid) == []

    def test_replace_rejects_malformed_typed_fields_before_wipe(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _edit(str(tmp_path), "card-add", uid, "survivor", "--meaning", "m",
                     "--commit").returncode == 0

        malformed_specs = [
            {"notebooks": [{"name": "N", "color": 123}]},
            {"notebooks": [{"name": "N", "cover_pattern": []}]},
            {"notebooks": [{"name": "N", "source_version": "one"}]},
            {"cards": [{"content": "w", "meaning": "m", "difficulty": "hard"}]},
            {"cards": [{"content": "w", "meaning": "m", "note": []}]},
            {"cards": [{"content": "w", "meaning": "m", "pos": {}}]},
        ]
        for spec in malformed_specs:
            result = self._seed(tmp_path, uid, spec, "--replace", "--commit", "--json")
            assert result.returncode != 0, spec
            assert _card_by_content(tmp_path, uid, "survivor") is not None, spec

    def test_rejects_duplicate_notebook_name(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = self._seed(tmp_path, uid,
                       {"notebooks": [{"name": "Dup"}, {"name": "Dup"}]},
                       "--commit", "--json")
        assert r.returncode != 0

    def test_idempotent_notebooks_and_counts(self, tmp_path):
        uid = _mk_user(tmp_path)
        spec = {
            "notebooks": [{"name": "Novel"}],
            "cards": [
                {"content": "ephemeral", "meaning": "短暫的", "notebook": "Novel"},
                {"content": "serendipity", "meaning": "意外之喜", "notebook": "Novel"},
            ],
        }
        r1 = self._seed(tmp_path, uid, spec, "--commit", "--json")
        assert r1.returncode == 0, r1.stderr
        d1 = json.loads(r1.stdout)["result"]
        assert d1["cards_added"] == 2

        r2 = self._seed(tmp_path, uid, spec, "--commit", "--json")
        assert r2.returncode == 0, r2.stderr
        d2 = json.loads(r2.stdout)["result"]
        # 第二次：notebook 不增殖、卡全為 dup。
        assert d2["cards_added"] == 0
        assert d2.get("skipped_dup") == 2
        names = [n["name"] for n in _notebook_rows(tmp_path, uid)]
        assert names.count("Novel") == 1

    def test_dup_card_upserts_meaning(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _edit(str(tmp_path), "card-add", uid, "ephemeral",
                     "--meaning", "舊義", "--commit").returncode == 0
        r = self._seed(tmp_path, uid,
                       {"cards": [{"content": "ephemeral", "meaning": "新義"}]},
                       "--commit", "--json")
        assert r.returncode == 0, r.stderr
        # dup 卡的核心欄位應被 upsert，而非靜默保留舊值。
        assert _card_by_content(tmp_path, uid, "ephemeral")["meaning"] == "新義"

    def test_link_cross_notebook_card_resolves(self, tmp_path):
        """seed 內 link 應能解析到本次建立的卡（不因 notebook 過濾而 false 失敗）。"""
        uid = _mk_user(tmp_path)
        spec = {
            "notebooks": [{"name": "NB"}],
            "cards": [
                {"content": "alpha", "meaning": "a", "notebook": "NB"},
                {"content": "beta", "meaning": "b", "notebook": "NB"},
            ],
            "links": [{"from": "alpha", "to": "beta", "kind": "shares_usage",
                       "confidence": 0.7, "reason": "r", "notebook": "NB"}],
        }
        r = self._seed(tmp_path, uid, spec, "--commit", "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)["result"]
        assert d["links_added"] == 1
        assert d["link_errors"] == []


# ── B4 / B6：input hygiene ──────────────────────────────────────


class TestInputHygiene:
    def test_notebook_create_rejects_path_chars(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _edit(str(tmp_path), "notebook-create", uid, "../../escape",
                  "--commit", "--json")
        assert r.returncode != 0

    def test_user_create_rejects_dot_prefix(self, tmp_path):
        r = _edit(str(tmp_path), "user-create", ".hidden", "--commit", "--json")
        assert r.returncode != 0


# ── A HIGH-3：card-update content 改值的同 notebook 衝突 ──────────


class TestCardUpdateContentConflict:
    def test_rejects_content_collision_same_notebook(self, tmp_path):
        uid = _mk_user(tmp_path)
        for w in ("alpha", "beta"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m",
                         "--commit").returncode == 0
        # 把 alpha 的 content 改成 beta（同 default notebook 已存在）→ 應擋。
        r = _edit(str(tmp_path), "card-update", uid, "alpha",
                  "--set", "content=beta", "--commit", "--json")
        assert r.returncode != 0
        # alpha 內容未被改動。
        assert _card_by_content(tmp_path, uid, "alpha") is not None


# ── A MED-5 / C5：card-set-review 時間不變量真的落盤 ──────────────


class TestReviewState:
    def test_due_time_invariant_on_disk(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _edit(str(tmp_path), "card-add", uid, "due_word", "--meaning", "m",
                     "--commit").returncode == 0
        r = _edit(str(tmp_path), "card-set-review", uid, "due_word",
                  "--state", "due", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["verified"]["ok"] is True
        card = _card_by_content(tmp_path, uid, "due_word")
        nxt = datetime.fromisoformat(card["next_review_at"])
        # SQLite 存無時區、讀回 naive；補 UTC 後才能與 aware now 比較（同工具 _as_utc）。
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=UTC)
        # due 卡的 next_review_at 必須在過去（TodayReview 撈得到）。
        assert nxt < datetime.now(UTC)

    def test_new_state_clears_next_review(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _edit(str(tmp_path), "card-add", uid, "nw", "--meaning", "m",
                     "--review", "due", "--commit").returncode == 0
        # 從 due 改回 new → next_review_at 應清空。
        r = _edit(str(tmp_path), "card-set-review", uid, "nw",
                  "--state", "new", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert _card_by_content(tmp_path, uid, "nw")["next_review_at"] is None


# ── C1：link 寫入真的落盤（verify 讀盤而非記憶體） ────────────────


class TestLinkPersistence:
    def test_link_add_persists_to_disk(self, tmp_path):
        uid = _mk_user(tmp_path)
        for w in ("x", "y"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m",
                         "--commit").returncode == 0
        r = _edit(str(tmp_path), "link-add", uid, "x", "y",
                  "--kind", "contrasts_with", "--confidence", "0.9",
                  "--reason", "r", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        lid = json.loads(r.stdout)["result"]["link"]["id"]
        # verify 報綠，磁碟必須真有這條 link。
        assert lid in {lk["id"] for lk in _graph_links(tmp_path, uid)}

    def test_link_add_idempotent_flagged(self, tmp_path):
        uid = _mk_user(tmp_path)
        for w in ("p", "q"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m",
                         "--commit").returncode == 0
        common = ("link-add", uid, "p", "q", "--kind", "shares_usage",
                  "--confidence", "0.5", "--reason", "r")
        assert _edit(str(tmp_path), *common, "--commit").returncode == 0
        r = _edit(str(tmp_path), *common, "--commit", "--json")
        assert r.returncode == 0, r.stderr
        # 撞既有 link 應顯式標記，不靜默假裝新建。
        assert json.loads(r.stdout)["result"].get("idempotent") is True

    def test_link_add_can_explicitly_update_existing(self, tmp_path):
        uid = _mk_user(tmp_path)
        for w in ("p2", "q2"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--commit").returncode == 0
        assert _edit(
            str(tmp_path), "link-add", uid, "p2", "q2",
            "--kind", "shares_usage", "--confidence", "0.5", "--reason", "r1",
            "--commit", "--json",
        ).returncode == 0
        r = _edit(
            str(tmp_path), "link-add", uid, "p2", "q2",
            "--kind", "contrasts_with", "--confidence", "0.95", "--reason", "r2",
            "--if-exists", "update", "--commit", "--json",
        )
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)["result"]
        assert out["existing_semantics"] == "updated-existing"
        p2 = _card_by_content(tmp_path, uid, "p2")
        q2 = _card_by_content(tmp_path, uid, "q2")
        assert p2 is not None and q2 is not None
        link = next(
            lk for lk in _graph_links(tmp_path, uid)
            if {lk["from_id"], lk["to_id"]} == {p2["id"], q2["id"]}
        )
        assert abs(link["confidence"] - 0.95) < 1e-6


# ── 完備性新指令：notebook-update/delete、card-move、link-update ──


class TestNewCommands:
    def test_notebook_update_renames(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "OldName")
        r = _edit(str(tmp_path), "notebook-update", uid, nb_id,
                  "--name", "NewName", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        names = [n["name"] for n in _notebook_rows(tmp_path, uid)]
        assert "NewName" in names and "OldName" not in names

    def test_notebook_delete_soft(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "ToDelete")
        r = _edit(str(tmp_path), "notebook-delete", uid, nb_id, "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert "ToDelete" not in [n["name"] for n in _notebook_rows(tmp_path, uid)]

    def test_notebook_delete_rejects_default(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _edit(str(tmp_path), "notebook-delete", uid, "default",
                  "--commit", "--json")
        assert r.returncode != 0

    def test_card_move_to_notebook(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "Target")
        assert _edit(str(tmp_path), "card-add", uid, "mover", "--meaning", "m",
                     "--commit").returncode == 0
        r = _edit(str(tmp_path), "card-move", uid, "mover",
                  "--to-notebook", "Target", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert _card_by_content(tmp_path, uid, "mover")["notebook_id"] == nb_id

    def test_card_move_rejects_unknown_notebook(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _edit(str(tmp_path), "card-add", uid, "stay", "--meaning", "m",
                     "--commit").returncode == 0
        r = _edit(str(tmp_path), "card-move", uid, "stay",
                  "--to-notebook", "Ghost", "--commit", "--json")
        assert r.returncode != 0
        assert _card_by_content(tmp_path, uid, "stay")["notebook_id"] == "default"

    def test_link_update_changes_confidence(self, tmp_path):
        uid = _mk_user(tmp_path)
        for w in ("m", "n"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "x",
                         "--commit").returncode == 0
        r = _edit(str(tmp_path), "link-add", uid, "m", "n",
                  "--kind", "shares_usage", "--confidence", "0.3",
                  "--reason", "orig", "--commit", "--json")
        lid = json.loads(r.stdout)["result"]["link"]["id"]
        r2 = _edit(str(tmp_path), "link-update", uid, lid,
                   "--confidence", "0.95", "--reason", "revised", "--commit", "--json")
        assert r2.returncode == 0, r2.stderr
        lk = next(lk for lk in _graph_links(tmp_path, uid) if lk["id"] == lid)
        assert abs(lk["confidence"] - 0.95) < 1e-6
        assert lk["reason"] == "revised"


# ── dry-run 仍零副作用（回歸護欄） ──────────────────────────────


class TestDryRunNoSideEffects:
    def test_card_add_dry_run_writes_nothing(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _edit(str(tmp_path), "card-add", uid, "phantom", "--meaning", "m", "--json")
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["committed"] is False
        assert _card_by_content(tmp_path, uid, "phantom") is None


# ── 第四輪 dogfood(D/E/F)修復回歸 ──────────────────────────────


class TestLinkSameNotebook:
    """link 嚴格 per-notebook:跨本連結被擋 + card-move 硬刪跨本 link。"""

    def test_link_add_cross_notebook_rejected_with_hint(self, tmp_path):
        uid = _mk_user(tmp_path)
        _mk_notebook(tmp_path, uid, "BookA")
        _mk_notebook(tmp_path, uid, "BookB")
        assert _edit(str(tmp_path), "card-add", uid, "alpha", "--meaning", "a",
                     "--notebook", "BookA", "--commit").returncode == 0
        assert _edit(str(tmp_path), "card-add", uid, "beta", "--meaning", "b",
                     "--notebook", "BookB", "--commit").returncode == 0
        # alpha 在 BookA、beta 在 BookB,在 BookA 內連 → beta 不在本本 → 擋 + 提示在哪本
        r = _edit(str(tmp_path), "link-add", uid, "alpha", "beta",
                  "--kind", "shares_usage", "--confidence", "0.5", "--reason", "r",
                  "--notebook", "BookA", "--commit", "--json")
        assert r.returncode != 0
        assert "notebook" in (r.stdout + r.stderr).lower()

    def test_card_move_purges_cross_notebook_links(self, tmp_path):
        uid = _mk_user(tmp_path)
        _mk_notebook(tmp_path, uid, "Src")
        _mk_notebook(tmp_path, uid, "Dst")
        for w in ("ml", "nl"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m",
                         "--notebook", "Src", "--commit").returncode == 0
        assert _edit(str(tmp_path), "link-add", uid, "ml", "nl",
                     "--kind", "shares_usage", "--confidence", "0.7", "--reason", "r",
                     "--notebook", "Src", "--commit", "--json").returncode == 0
        src_id = next(n["id"] for n in _notebook_rows(tmp_path, uid) if n["name"] == "Src")
        assert len(_graph_links(tmp_path, uid, src_id)) == 1
        # 搬 ml 到 Dst → 原 Src graph 的跨本 link 應被硬刪(維持「無跨本 link」不變量)
        rm = _edit(str(tmp_path), "card-move", uid, "ml", "--to-notebook", "Dst",
                   "--commit", "--json")
        assert rm.returncode == 0, rm.stderr
        assert json.loads(rm.stdout)["result"]["purged_count"] == 1
        assert len(_graph_links(tmp_path, uid, src_id)) == 0


class TestNotebookDeleteCascade:
    def test_rejects_nonempty_without_cascade(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "Full")
        assert _edit(str(tmp_path), "card-add", uid, "c1", "--meaning", "m",
                     "--notebook", "Full", "--commit").returncode == 0
        r = _edit(str(tmp_path), "notebook-delete", uid, nb_id, "--commit", "--json")
        assert r.returncode != 0  # 非空拒絕,避免孤兒卡
        assert "Full" in [n["name"] for n in _notebook_rows(tmp_path, uid)]

    def test_cascade_soft_deletes_cards(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "Full")
        assert _edit(str(tmp_path), "card-add", uid, "c1", "--meaning", "m",
                     "--notebook", "Full", "--commit").returncode == 0
        r = _edit(str(tmp_path), "notebook-delete", uid, nb_id, "--cascade",
                  "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert "Full" not in [n["name"] for n in _notebook_rows(tmp_path, uid)]
        assert _card_by_content(tmp_path, uid, "c1") is None  # 卡一併軟刪,無孤兒


class TestResolverIdPriority:
    def test_id_takes_priority_over_name(self, tmp_path):
        uid = _mk_user(tmp_path)
        id_a = _mk_notebook(tmp_path, uid, "BookA")
        # 建一本 name 恰好等於 BookA 的 hex id → 傳該字串應解析到 id 那本(非 name 那本)
        _mk_notebook(tmp_path, uid, id_a)
        assert _edit(str(tmp_path), "card-add", uid, "x", "--meaning", "m",
                     "--notebook", id_a, "--commit").returncode == 0
        assert _card_by_content(tmp_path, uid, "x")["notebook_id"] == id_a


class TestSeedFourthRound:
    def _seed(self, tmp_path, uid, spec, *extra):
        p = tmp_path / "spec.json"
        p.write_text(json.dumps(spec))
        return _edit(str(tmp_path), "seed", uid, str(p), *extra)

    def test_dry_run_prevalidates_kind(self, tmp_path):
        uid = _mk_user(tmp_path)
        # 非法 kind dry-run(不帶 --commit)也應提前報錯,不必等 commit 才爆
        r = self._seed(tmp_path, uid,
            {"cards": [{"content": "a", "meaning": "m"}, {"content": "b", "meaning": "m"}],
             "links": [{"from": "a", "to": "b", "kind": "BOGUS",
                        "confidence": 0.5, "reason": "r"}]}, "--json")
        assert r.returncode != 0

    def test_cross_notebook_same_content_verify_ok(self, tmp_path):
        uid = _mk_user(tmp_path)
        # 兩本各一張同 content 不同 meaning → 都正確建好,verify 不該 false-positive
        r = self._seed(tmp_path, uid,
            {"notebooks": [{"name": "A"}, {"name": "B"}],
             "cards": [{"content": "same", "meaning": "defA", "notebook": "A"},
                       {"content": "same", "meaning": "defB", "notebook": "B"}]},
            "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["verified"]["ok"] is True

    def test_clears_empty_examples_on_rerun(self, tmp_path):
        uid = _mk_user(tmp_path)
        self._seed(tmp_path, uid,
            {"cards": [{"content": "w", "meaning": "m", "examples": ["ex1", "ex2"]}]},
            "--commit")
        assert _card_field(tmp_path, uid, "w", "examples") == ["ex1", "ex2"]
        # 第二次明確設 examples=[] → 清空(區分省略 vs 明確設空)
        self._seed(tmp_path, uid,
            {"cards": [{"content": "w", "meaning": "m", "examples": []}]}, "--commit")
        assert _card_field(tmp_path, uid, "w", "examples") == []

    def test_review_anchor_makes_review_timestamps_deterministic(self, tmp_path):
        uid = _mk_user(tmp_path)
        spec = {
            "review_anchor": "2026-06-06T00:00:00Z",
            "cards": [
                {"content": "due", "meaning": "m",
                 "review": {"state": "due", "interval": 24}},
                {"content": "reviewed", "meaning": "m",
                 "review": {"state": "reviewed", "interval": 48}},
            ],
        }
        r1 = self._seed(tmp_path, uid, spec, "--commit", "--json")
        assert r1.returncode == 0, r1.stderr
        due = _card_by_content(tmp_path, uid, "due")
        reviewed = _card_by_content(tmp_path, uid, "reviewed")
        assert due["last_reviewed_at"].startswith("2026-06-04 23:00:00")
        assert due["next_review_at"].startswith("2026-06-05 23:00:00")
        assert reviewed["last_reviewed_at"].startswith("2026-06-06 00:00:00")
        assert reviewed["next_review_at"].startswith("2026-06-08 00:00:00")

        r2 = self._seed(tmp_path, uid, spec, "--commit", "--json")
        assert r2.returncode == 0, r2.stderr
        assert _card_by_content(tmp_path, uid, "due")["next_review_at"] == due["next_review_at"]
        assert _card_by_content(tmp_path, uid, "reviewed")["next_review_at"] == reviewed["next_review_at"]

    def test_review_anchor_can_be_overridden_per_card(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = self._seed(tmp_path, uid, {
            "review_anchor": "2026-06-06T00:00:00Z",
            "cards": [
                {"content": "local", "meaning": "m",
                 "review": {"state": "reviewed", "interval": 24,
                            "anchor": "2026-06-10T12:00:00Z"}},
            ],
        }, "--commit", "--json")
        assert r.returncode == 0, r.stderr
        row = _card_by_content(tmp_path, uid, "local")
        assert row["last_reviewed_at"].startswith("2026-06-10 12:00:00")
        assert row["next_review_at"].startswith("2026-06-11 12:00:00")

    def test_seed_can_write_source_context(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = self._seed(tmp_path, uid, {
            "cards": [{
                "content": "w",
                "meaning": "m",
                "source": {"type": "book", "title": "Demo Book", "chapter": "Chapter 1"},
            }],
        }, "--commit", "--json")
        assert r.returncode == 0, r.stderr
        source = json.loads(_card_by_content(tmp_path, uid, "w")["source"])
        assert source == {"type": "book", "title": "Demo Book", "chapter": "Chapter 1"}

    def test_bundled_marketing_seed_is_good_showcase_data(self, tmp_path):
        uid = _mk_user(tmp_path)
        spec = Path(__file__).resolve().parents[2] / "ops" / "seeds" / "marketing_demo.json"
        r = _edit(str(tmp_path), "seed", uid, str(spec), "--commit", "--json")
        assert r.returncode == 0, r.stderr

        rows = _card_rows(tmp_path, uid)
        assert len(rows) == 12
        counts = {0: 0, 1: 0, 2: 0}
        for row in rows:
            counts[row["review_count"]] = counts.get(row["review_count"], 0) + 1
        assert counts[0] == 4, "marketing seed 應保留 4 張 new 卡給未學習畫面"
        assert counts[1] == 4, "marketing seed 應保留 4 張 due 卡給 Today Review"
        assert counts[2] == 4, "marketing seed 應保留 4 張 reviewed 卡給已學習狀態"

        notebooks = _notebook_rows(tmp_path, uid)
        names = {nb["name"] for nb in notebooks}
        assert {"Editorial Picks", "Systems Thinking", "Creative Practice"} <= names

        total_links = 0
        for nb in ("Editorial Picks", "Systems Thinking", "Creative Practice"):
            nb_id = next(row["id"] for row in notebooks if row["name"] == nb)
            total_links += len(_graph_links(tmp_path, uid, nb_id))
        assert total_links == 6


class TestIntervalValidation:
    def test_negative_interval_rejected(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _edit(str(tmp_path), "card-add", uid, "w", "--meaning", "m",
                     "--commit").returncode == 0
        r = _edit(str(tmp_path), "card-set-review", uid, "w", "--state", "reviewed",
                  "--interval", "-5", "--commit", "--json")
        assert r.returncode != 0
        assert "間隔" in (r.stdout + r.stderr) or "> 0" in (r.stdout + r.stderr)


class TestLinkListAndMoveAlias:
    def test_link_list_returns_ids(self, tmp_path):
        uid = _mk_user(tmp_path)
        for w in ("p", "q"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m",
                         "--commit").returncode == 0
        ra = _edit(str(tmp_path), "link-add", uid, "p", "q", "--kind", "shares_usage",
                   "--confidence", "0.6", "--reason", "r", "--commit", "--json")
        lid = json.loads(ra.stdout)["result"]["link"]["id"]
        r = _edit(str(tmp_path), "link-list", uid, "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] == 1 and d["links"][0]["id"] == lid
        assert {d["links"][0]["from"], d["links"][0]["to"]} == {"p", "q"}

    def test_card_move_notebook_alias(self, tmp_path):
        uid = _mk_user(tmp_path)
        dst = _mk_notebook(tmp_path, uid, "Dest")
        assert _edit(str(tmp_path), "card-add", uid, "mv", "--meaning", "m",
                     "--commit").returncode == 0
        # 用 --notebook(alias)而非 --to-notebook
        r = _edit(str(tmp_path), "card-move", uid, "mv", "--notebook", "Dest",
                  "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert _card_by_content(tmp_path, uid, "mv")["notebook_id"] == dst


class TestMarketingSurfaceShaping:
    def test_notebook_update_can_set_sort_order(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "Marketing")
        r = _edit(
            str(tmp_path), "notebook-update", uid, nb_id,
            "--sort-order", "-10", "--commit", "--json"
        )
        assert r.returncode == 0, r.stderr
        notebook = next(nb for nb in _notebook_rows(tmp_path, uid) if nb["id"] == nb_id)
        assert notebook["sort_order"] == -10

    def test_user_config_set_can_shape_settings_surface(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "Promo Focus")
        r = _edit(
            str(tmp_path), "user-config-set", uid,
            "--translation-source", "en",
            "--translation-target", "ja",
            "--review-clock", "paused",
            "--paused-at", "2026-06-07T09:30:00Z",
            "--review-mode", "custom",
            "--custom-initial-interval-hours", "18",
            "--custom-remembered-multiplier", "2.1",
            "--custom-forgot-multiplier", "0.4",
            "--custom-minimum-interval-hours", "8",
            "--custom-maximum-interval-hours", "720",
            "--active-notebook", "Promo Focus",
            "--commit", "--json",
        )
        assert r.returncode == 0, r.stderr

        cfg = _cli(str(tmp_path), "user-config", uid, "--json")
        assert cfg.returncode == 0, cfg.stderr
        data = json.loads(cfg.stdout)["config"]
        assert data["translation"]["source_lang"] == "en"
        assert data["translation"]["target_lang"] == "ja"
        assert data["review_clock"]["is_paused"] is True
        assert data["review_clock"]["paused_at"] == "2026-06-07T09:30:00Z"
        assert data["review_mode"]["mode"] == "custom"
        assert data["review_mode"]["custom_initial_interval_hours"] == 18
        assert data["review_mode"]["custom_remembered_multiplier"] == 2.1
        assert data["review_mode"]["custom_forgot_multiplier"] == 0.4
        assert data["review_mode"]["custom_minimum_interval_hours"] == 8
        assert data["review_mode"]["custom_maximum_interval_hours"] == 720
        assert data["vocab_ui"]["active_notebook_id"] == nb_id


class TestLinkDelete:
    def test_link_delete_removes_from_disk(self, tmp_path):
        uid = _mk_user(tmp_path)
        for w in ("a", "b"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m",
                         "--commit").returncode == 0
        ra = _edit(str(tmp_path), "link-add", uid, "a", "b",
                   "--kind", "shares_usage", "--confidence", "0.5",
                   "--reason", "r", "--commit", "--json")
        assert ra.returncode == 0, ra.stderr
        lid = json.loads(ra.stdout)["result"]["link"]["id"]
        assert any(lk["id"] == lid for lk in _graph_links(tmp_path, uid))

        rd = _edit(str(tmp_path), "link-delete", uid, lid,
                   "--commit", "--json")
        assert rd.returncode == 0, rd.stderr
        assert not any(lk["id"] == lid for lk in _graph_links(tmp_path, uid))

    def test_link_delete_rejects_missing_link(self, tmp_path):
        uid = _mk_user(tmp_path)
        fake_lid = "link-does-not-exist-1234"
        rd = _edit(str(tmp_path), "link-delete", uid, fake_lid,
                   "--commit", "--json")
        assert rd.returncode != 0
        assert "link" in (rd.stdout + rd.stderr).lower()


class TestLinkUpdateErrors:
    def test_link_update_rejects_missing_link(self, tmp_path):
        uid = _mk_user(tmp_path)
        fake_lid = "link-does-not-exist-5678"
        ru = _edit(str(tmp_path), "link-update", uid, fake_lid,
                   "--confidence", "0.9", "--commit", "--json")
        assert ru.returncode != 0
        assert "link" in (ru.stdout + ru.stderr).lower()


# ── IMP-0024:seed --replace(spec = 精確最終狀態)+ verify 形狀比對 ──────
#
# 兩半缺一不可:additive seed 對「同 content 換本」會新增第二張卡(CardStore.add
# 查重綁 (content, notebook_id)),而舊 verify 判準 `total >= len(cards)` 讓那張
# 多出來的重複卡照樣報綠。所以本 class 既釘住 replace 的資料面,也釘住 verify
# 必須能看見 extra/missing。


class TestSeedReplace:
    def _seed(self, tmp_path, uid, spec, *extra):
        p = tmp_path / "spec.json"
        p.write_text(json.dumps(spec))
        return _edit(str(tmp_path), "seed", uid, str(p), *extra)

    def test_replace_moves_card_between_notebooks_without_duplicating(self, tmp_path):
        uid = _mk_user(tmp_path)
        spec_a = {"notebooks": [{"name": "A"}],
                  "cards": [{"content": "w", "meaning": "m", "notebook": "A"}]}
        spec_b = {"notebooks": [{"name": "B"}],
                  "cards": [{"content": "w", "meaning": "m", "notebook": "B"}]}
        r0 = self._seed(tmp_path, uid, spec_a, "--commit", "--json")
        assert r0.returncode == 0, r0.stderr
        r1 = self._seed(tmp_path, uid, spec_b, "--replace", "--commit", "--json")
        assert r1.returncode == 0, r1.stdout + r1.stderr

        rows = _card_rows(tmp_path, uid)
        assert len(rows) == 1, rows
        nbs = _notebook_rows(tmp_path, uid)
        # notebooks.db 必須讀得回 B —— 若 wipe 寫在建 nb_store 之後,store 會持有
        # 被刪掉的 inode,寫入落到孤兒檔,這條讀盤斷言就轉紅。
        nb_b = next((n for n in nbs if n["name"] == "B"), None)
        assert nb_b is not None, nbs
        assert rows[0]["notebook_id"] == nb_b["id"]
        # 舊本 A 屬於被取代的舊狀態,replace 後不該還在。
        assert [n for n in nbs if n["name"] == "A"] == []

        # 對照組:不帶 --replace 的同序列必須維持 additive 語意(2 張卡)。
        uid2 = _mk_user(tmp_path, "demo2")
        r2 = self._seed(tmp_path, uid2, spec_a, "--commit", "--json")
        assert r2.returncode == 0, r2.stderr
        r3 = self._seed(tmp_path, uid2, spec_b, "--commit", "--json")
        assert r3.returncode == 0, r3.stdout + r3.stderr
        assert len(_card_rows(tmp_path, uid2)) == 2

    def test_replace_dry_run_does_not_touch_disk(self, tmp_path):
        import hashlib

        uid = _mk_user(tmp_path)
        r0 = self._seed(tmp_path, uid,
                        {"cards": [{"content": "w", "meaning": "m"}]}, "--commit", "--json")
        assert r0.returncode == 0, r0.stderr
        # 快照整個 user_dir 而非單一 cards.db:plan 期 `_count_active_cards` 以
        # mode=ro 開檔,SQLite 在「有 -wal 無 -shm」時會重建 -shm 旁檔,而它跑在
        # plan["wipe_files"] 之後 —— 只 hash cards.db 看不到這種副作用。
        def _snapshot():
            d = _user_dir(tmp_path, uid)
            return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(d.iterdir()) if p.is_file()}

        before = _snapshot()
        assert "cards.db" in before

        r1 = self._seed(tmp_path, uid,
                        {"cards": [{"content": "other", "meaning": "m2"}]}, "--replace", "--json")
        assert r1.returncode == 0, r1.stdout + r1.stderr
        after = _snapshot()
        # 既有檔一 byte 未變。
        assert {k: v for k, v in after.items() if k in before} == before
        # dry-run 只可能多出 SQLite 讀 WAL 模式 DB 時重建的旁檔,不得多出別的。
        new_files = set(after) - set(before)
        assert all(n.endswith(("-wal", "-shm")) for n in new_files), new_files
        plan = json.loads(r1.stdout)["plan"]
        assert plan["replace"] is True
        assert "cards.db" in plan["wipe_files"], plan
        assert plan["target_active_cards_before"] == 1
        # 那些旁檔一樣會被 wipe 刪掉,所以必須出現在預覽裡 —— 預覽少報等於沒預覽。
        assert new_files <= set(plan["wipe_files"]), (new_files, plan["wipe_files"])

    def test_replace_verify_reports_exact_shape(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = self._seed(tmp_path, uid,
                       {"notebooks": [{"name": "A"}],
                        "cards": [{"content": "alpha", "meaning": "m1", "notebook": "A"},
                                  {"content": "beta", "meaning": "m2", "notebook": "A"}]},
                       "--replace", "--commit", "--json")
        assert r.returncode == 0, r.stdout + r.stderr
        verified = json.loads(r.stdout)["verified"]
        assert verified["ok"] is True
        assert verified["extra_cards"] == []
        assert verified["missing_cards"] == []
        assert verified["total_cards"] == 2

    def test_replace_rebuilds_default_notebook(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = self._seed(tmp_path, uid,
                       {"cards": [{"content": "plain", "meaning": "m"}]},
                       "--replace", "--commit", "--json")
        assert r.returncode == 0, r.stdout + r.stderr
        card = _card_by_content(tmp_path, uid, "plain")
        assert card is not None
        assert card["notebook_id"] == "default"
        assert [n for n in _notebook_rows(tmp_path, uid) if n["id"] == "default"]

    def test_seed_shape_diff_detects_extra_and_missing(self, tmp_path):
        # 函式內 import:實作落地前 module 尚無此符號,放檔頭會讓整個 test 檔
        # 收集失敗、連累無關測試。
        from kg.ops_edit_seed_commands import _seed_shape_diff

        expected = [{"nb_id": "n1", "content": "Alpha", "meaning": ""},
                    {"nb_id": "n2", "content": "beta", "meaning": ""}]
        actual = [("n1", "alpha"), ("n2", "gamma")]
        extra, missing = _seed_shape_diff(expected, actual)
        # Alpha/alpha 經 normalize_nfc_lower 視為同一張 → 不進 extra/missing。
        assert extra == ["gamma@n2"]
        assert missing == ["beta@n2"]

    def test_replace_verdict_rejects_leftover_duplicate(self, tmp_path):
        # 這條判準只有「wipe 沒清乾淨」時才轉紅,而那個狀態走 CLI 產不出來
        # (cards 只住 cards.db,wipe 必清它)。所以直接餵髒狀態給純函式,
        # 否則這道守衛平時無人執行 —— 沒人查的判準等於假的。
        from kg.ops_edit_seed_commands import _seed_replace_verdict

        expected = [{"nb_id": "nbB", "content": "w", "meaning": "m"}]
        # 殘留:舊本 nbA 的 w 沒被清掉,新本 nbB 又建了一張 → 重複卡。
        dirty = _seed_replace_verdict(expected, [("nbA", "w"), ("nbB", "w")],
                                      link_errors=[], field_mismatches=[],
                                      dangling_config=[])
        assert dirty["ok"] is False
        assert dirty["extra_cards"] == ["w@nbA"]
        assert dirty["missing_cards"] == []
        # 卡留在舊本、新本沒建(換分類只做了一半):筆數**對得上**,只有集合差抓得到。
        misplaced = _seed_replace_verdict(expected, [("nbA", "w")],
                                          link_errors=[], field_mismatches=[],
                                          dangling_config=[])
        assert misplaced["ok"] is False
        assert misplaced["extra_cards"] == ["w@nbA"]
        assert misplaced["missing_cards"] == ["w@nbB"]
        # 大小寫變體重複(同本 w + W):正規化後兩者 key 相同,集合差**看不見**它,
        # 只有「筆數要對得上」那一半抓得到。兩個 clause 各抓一種重複形狀,缺一不可。
        case_dupe = _seed_replace_verdict(expected, [("nbB", "w"), ("nbB", "W")],
                                          link_errors=[], field_mismatches=[],
                                          dangling_config=[])
        assert case_dupe["ok"] is False
        assert case_dupe["extra_cards"] == []
        assert case_dupe["missing_cards"] == []
        # 乾淨狀態才給綠 —— 沒有正控的沉默不能當通過。
        clean = _seed_replace_verdict(expected, [("nbB", "w")],
                                      link_errors=[], field_mismatches=[],
                                      dangling_config=[])
        assert clean["ok"] is True
        assert clean["extra_cards"] == []

    def test_replace_rejects_undeclared_notebook_ref_before_wiping(self, tmp_path):
        # replace 會清掉「既存 notebook」這個合法參照來源,所以引用既存本的 spec
        # 在 replace 下必須**在 wipe 之前**就紅。否則 dry-run 報綠、--commit 清空
        # 整層後才在 _resolve_nb 撞紅,而錯誤輸出還寫著 "committed": false。
        uid = _mk_user(tmp_path)
        r0 = self._seed(tmp_path, uid,
                        {"notebooks": [{"name": "A"}],
                         "cards": [{"content": "w", "meaning": "m", "notebook": "A"}]},
                        "--commit", "--json")
        assert r0.returncode == 0, r0.stderr
        # spec 未宣告 A,卻用 A 當 card 的 notebook。
        undeclared = {"cards": [{"content": "z", "meaning": "m2", "notebook": "A"}]}
        rd = self._seed(tmp_path, uid, undeclared, "--replace", "--json")
        assert rd.returncode != 0, rd.stdout
        assert "A" in (rd.stdout + rd.stderr)
        rc = self._seed(tmp_path, uid, undeclared, "--replace", "--commit", "--json")
        assert rc.returncode != 0
        # 讀盤,不看工具自述:舊資料必須原封不動(wipe 根本不該發生)。
        rows = _card_rows(tmp_path, uid)
        assert [r["content"] for r in rows] == ["w"], rows
        assert [n["name"] for n in _notebook_rows(tmp_path, uid) if n["name"] == "A"] == ["A"]

    def test_replace_allows_reference_to_default_and_declared(self, tmp_path):
        # 正控:未加這道檢查前上面那條也會綠(它靠 _resolve_nb 事後爆)。這條確保
        # 新檢查沒有把合法的 spec 一起擋掉 —— 沒有正控的沉默不算通過。
        uid = _mk_user(tmp_path)
        r = self._seed(tmp_path, uid,
                       {"notebooks": [{"name": "B"}],
                        "cards": [{"content": "x", "meaning": "m", "notebook": "B"},
                                  {"content": "x2", "meaning": "m", "notebook": "B"},
                                  {"content": "y", "meaning": "m", "notebook": "default"},
                                  {"content": "q", "meaning": "m"}],
                        "links": [{"from": "x", "to": "x2", "kind": "shares_usage",
                                   "confidence": 0.5, "reason": "r", "notebook": "B"}]},
                       "--replace", "--commit", "--json")
        assert r.returncode == 0, r.stdout + r.stderr
        verified = json.loads(r.stdout)["verified"]
        assert verified["ok"] is True, verified
        assert verified["link_errors"] == []
        assert sorted(c["content"] for c in _card_rows(tmp_path, uid)) == ["q", "x", "x2", "y"]

    def test_replace_reports_dangling_active_notebook(self, tmp_path):
        # --replace 刻意不動 identity/users.json,於是 active notebook 指標會指向
        # 剛被清掉的舊 id。卡的形狀完全正確,只看卡就會報綠 —— 這是同族的第三種
        # 說謊,demo 帳號「新選詞歸哪本」實際上懸空。
        uid = _mk_user(tmp_path)
        r0 = self._seed(tmp_path, uid,
                        {"notebooks": [{"name": "A"}],
                         "cards": [{"content": "w", "meaning": "m", "notebook": "A"}]},
                        "--commit", "--json")
        assert r0.returncode == 0, r0.stderr
        old_id = next(n["id"] for n in _notebook_rows(tmp_path, uid) if n["name"] == "A")
        rc = _edit(str(tmp_path), "user-config-set", uid, "--active-notebook", "A",
                   "--commit", "--json")
        assert rc.returncode == 0, rc.stderr

        r1 = self._seed(tmp_path, uid,
                        {"notebooks": [{"name": "B"}],
                         "cards": [{"content": "w", "meaning": "m", "notebook": "B"}]},
                        "--replace", "--commit", "--json")
        verified = json.loads(r1.stdout)["verified"]
        # 卡的形狀是對的 —— 正是「只看卡會報綠」的那一半。
        assert verified["extra_cards"] == []
        assert verified["missing_cards"] == []
        # 但整體判準必須紅,而且要指名是誰懸空。
        assert verified["ok"] is False, verified
        assert len(verified["dangling_config"]) == 1, verified
        msg = verified["dangling_config"][0]
        # 指名是誰懸空(那個 id 由上面的 _notebook_rows 讀盤取得,非工具回顯)…
        assert f"vocab_ui.active_notebook_id={old_id}" in msg
        # …並且指路,否則 operator 只知道紅、不知道怎麼修。
        assert "user-config-set" in msg
        assert r1.returncode == 1

    def test_replace_clean_run_has_no_dangling_config(self, tmp_path):
        # 正控:沒設過 active notebook 的帳號不該被這道檢查誤傷。
        uid = _mk_user(tmp_path)
        r = self._seed(tmp_path, uid,
                       {"notebooks": [{"name": "B"}],
                        "cards": [{"content": "w", "meaning": "m", "notebook": "B"}]},
                       "--replace", "--commit", "--json")
        assert r.returncode == 0, r.stdout + r.stderr
        verified = json.loads(r.stdout)["verified"]
        assert verified["dangling_config"] == []
        assert verified["ok"] is True
        assert verified["expected_cards"] == 1

    def test_replace_survives_unreadable_users_json(self, tmp_path):
        # verify_fn 是第一個嚴格讀 users.json 的地方,而它跑在 EditContext 的
        # try/except **之外**、且在破壞性 wipe 已落地之後。裸 traceback 會噴上
        # --json stdout(cmd_seed 自己為 spec 解析捍衛過同一條契約),operator 會
        # 拿到空 stdout 卻已經沒有資料。壞掉必須是**具名的紅**,不是 crash。
        uid = _mk_user(tmp_path)
        spec = {"notebooks": [{"name": "B"}],
                "cards": [{"content": "w", "meaning": "m", "notebook": "B"}]}
        (tmp_path / "users.json").write_text("{ this is not json")
        r = self._seed(tmp_path, uid, spec, "--replace", "--commit", "--json")
        # stdout 仍是合法 JSON —— 這條斷言碰的字串是 CLI 的 stdout 本身。
        payload = json.loads(r.stdout)
        assert payload["verified"]["ok"] is False
        assert any("users.json" in s for s in payload["verified"]["dangling_config"]), payload
        assert r.returncode == 1

    def test_replace_rejects_non_string_active_notebook(self, tmp_path):
        # isinstance 階梯守住每一層 dict 卻沒守葉子值時,`active_nb in live_nb_ids`
        # 會以 unhashable TypeError 炸在同一個 try 之外。
        uid = _mk_user(tmp_path)
        users = json.loads((tmp_path / "users.json").read_text())
        users[uid].setdefault("config", {})["vocab_ui"] = {"active_notebook_id": {"oops": 1}}
        (tmp_path / "users.json").write_text(json.dumps(users))
        r = self._seed(tmp_path, uid,
                       {"notebooks": [{"name": "B"}],
                        "cards": [{"content": "w", "meaning": "m", "notebook": "B"}]},
                       "--replace", "--commit", "--json")
        payload = json.loads(r.stdout)
        assert payload["verified"]["ok"] is False
        assert any("型別非法" in s for s in payload["verified"]["dangling_config"]), payload
        assert r.returncode == 1
