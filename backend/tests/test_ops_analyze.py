"""ops_analyze.py — 計價走 kg.quota_service.token_cost_usd 的 smoke 測試。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from ops_helpers import _create_token_usage_db, _now_iso

SCRIPT = Path(__file__).resolve().parent.parent / "ops_analyze.py"


def _setup_user(tmp_path: Path, uid: str) -> Path:
    udir = tmp_path / "users" / uid
    udir.mkdir(parents=True)
    conn = sqlite3.connect(str(udir / "cards.db"))
    conn.execute("CREATE TABLE card (id TEXT PRIMARY KEY, content TEXT, meaning TEXT, is_deleted INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO card VALUES ('c1', 'hello', '你好', 0)")
    conn.commit()
    conn.close()
    (udir / "graph_default.json").write_text("[]")
    return udir


def _run(data_dir: str, *args: str) -> subprocess.CompletedProcess:
    """執行 ops_analyze.py，設定 KG_DATA_DIR + PYTHONPATH。

    子程序可能跑在裸 python（非專案 venv），缺 PYTHONPATH 則 `import kg.*` 失敗。
    """
    env = {
        **os.environ,
        "KG_DATA_DIR": data_dir,
        "PYTHONPATH": str(SCRIPT.parent / "src"),
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
    )


class TestLevel1:
    def test_level_1_smoke(self, tmp_path):
        _setup_user(tmp_path, "user1")
        _create_token_usage_db(
            tmp_path,
            [
                ("user1", "translate", 1_000_000, 1_000_000, _now_iso()),
            ],
            with_provider=False,
        )
        result = _run(str(tmp_path), "user1", "1")
        assert result.returncode == 0
        # gemini routed: 0.10 + 0.40 = 0.5000
        assert "0.5000" in result.stdout


class TestLevel2:
    def test_level_2_smoke(self, tmp_path):
        _setup_user(tmp_path, "user1")
        _create_token_usage_db(
            tmp_path,
            [
                ("user1", "translate", 1_000_000, 1_000_000, _now_iso()),
            ],
            with_provider=False,
        )
        result = _run(str(tmp_path), "user1", "2")
        assert result.returncode == 0
        assert "0.5000" in result.stdout


class TestProviderAware:
    def test_deepseek_priced_provider_aware(self, tmp_path):
        """provider='deepseek' row → deepseek 費率 0.42,非 gemini 0.50。"""
        _setup_user(tmp_path, "user1")
        _create_token_usage_db(
            tmp_path,
            [
                ("user1", "translate", 1_000_000, 1_000_000, _now_iso(), "deepseek"),
            ],
            with_provider=True,
        )
        result = _run(str(tmp_path), "user1", "2")
        assert result.returncode == 0
        assert "0.4200" in result.stdout

    def test_legacy_no_provider_column(self, tmp_path):
        """無 provider 欄 → gemini fallback,不報錯。"""
        _setup_user(tmp_path, "user1")
        _create_token_usage_db(
            tmp_path,
            [
                ("user1", "translate", 1_000_000, 1_000_000, _now_iso()),
            ],
            with_provider=False,
        )
        result = _run(str(tmp_path), "user1", "1")
        assert result.returncode == 0
        assert "0.5000" in result.stdout


def _link(lid: str, a: str, b: str, status: str | None = "active") -> dict:
    link = {
        "id": lid,
        "from_id": a,
        "to_id": b,
        "kind": "synonym",
        "confidence": 0.9,
        "created_at": _now_iso(),
    }
    if status is not None:
        link["status"] = status
    return link


def _setup_multi_notebook(tmp_path: Path, uid: str = "user1") -> Path:
    """default: d1,d2 active + dx deleted；work: w1 active。embeddings 全齊。"""
    import json

    import numpy as np

    udir = tmp_path / "users" / uid
    udir.mkdir(parents=True)
    conn = sqlite3.connect(str(udir / "cards.db"))
    conn.execute(
        "CREATE TABLE card (id TEXT PRIMARY KEY, content TEXT, meaning TEXT, "
        "is_deleted INTEGER DEFAULT 0, notebook_id TEXT DEFAULT 'default')"
    )
    conn.executemany(
        "INSERT INTO card VALUES (?, ?, ?, ?, ?)",
        [
            ("d1", "alpha", "甲", 0, "default"),
            ("d2", "beta", "乙", 0, "default"),
            ("dx", "gone", "沒了", 1, "default"),
            ("w1", "work", "工作", 0, "work"),
        ],
    )
    conn.commit()
    conn.close()
    links = [
        _link("lnk-active-0001", "d1", "d2"),
        _link("lnk-deprec-0001", "d1", "dx", "deprecated"),
        _link("lnk-hidden-0001", "d2", "dx", "hidden"),
        _link("lnk-legacy-0001", "d2", "d1", None),
    ]
    (udir / "graph_default.json").write_text(json.dumps(links))
    (udir / "card_ids_default.json").write_text(json.dumps(["d1", "d2"]))
    np.save(str(udir / "embeddings_default.npy"), np.eye(2, 4))
    (udir / "card_ids_work.json").write_text(json.dumps(["w1"]))
    np.save(str(udir / "embeddings_work.npy"), np.eye(1, 4))
    return udir


class TestActiveLinksAndDefaultNotebook:
    def test_l6_ignores_deprecated_link_to_deleted_card(self, tmp_path):
        _setup_multi_notebook(tmp_path)
        out = _run(str(tmp_path), "user1", "6").stdout
        assert "已刪除但連結仍 active" not in out
        assert "指向已刪除卡片" not in out

    def test_l6_reports_active_link_to_deleted_card(self, tmp_path):
        import json

        udir = _setup_multi_notebook(tmp_path)
        gp = udir / "graph_default.json"
        links = json.loads(gp.read_text()) + [_link("lnk-act-del-001", "d1", "dx")]
        gp.write_text(json.dumps(links))
        out = _run(str(tmp_path), "user1", "6").stdout
        assert "已刪除但連結仍 active" in out
        assert "1 條連結指向已刪除卡片" in out

    def test_l6_no_missing_embedding_for_any_notebook(self, tmp_path):
        _setup_multi_notebook(tmp_path)
        out = _run(str(tmp_path), "user1", "6").stdout
        assert "缺 embedding" not in out
        assert "已刪除卡片仍佔 embedding" not in out

    def test_l6_missing_embedding_counts_default_notebook(self, tmp_path):
        import json

        udir = _setup_multi_notebook(tmp_path)
        (udir / "card_ids_default.json").write_text(json.dumps(["d1"]))
        out = _run(str(tmp_path), "user1", "6").stdout
        assert "1 張 active 卡片缺 embedding (default notebook)" in out

    def test_l6_dupe_and_self_ignore_non_active(self, tmp_path):
        import json

        udir = _setup_multi_notebook(tmp_path)
        gp = udir / "graph_default.json"
        links = json.loads(gp.read_text()) + [
            _link("lnk-dep-self-01", "d1", "d1", "deprecated"),
            _link("lnk-hid-dupe-01", "d1", "d2", "hidden"),
        ]
        gp.write_text(json.dumps(links))
        out = _run(str(tmp_path), "user1", "6").stdout
        assert "自連結" not in out
        # active d1-d2 與 legacy(無 status) d2-d1 仍算 1 組重複
        assert "1 條重複連結" in out

    def test_l5_coverage_per_notebook(self, tmp_path):
        _setup_multi_notebook(tmp_path)
        out = _run(str(tmp_path), "user1", "5").stdout
        assert "2/2 active cards (100%)" in out
        assert "[default notebook]" in out

    def test_l1_link_count_is_active_only(self, tmp_path):
        _setup_multi_notebook(tmp_path)
        out = _run(str(tmp_path), "user1", "1").stdout
        assert "active links: 2" in out
        assert "deprecated links: 1" in out
        assert "hidden links: 1" in out

    def test_l3_edges_ignore_non_active(self, tmp_path):
        _setup_multi_notebook(tmp_path)
        out = _run(str(tmp_path), "user1", "3").stdout
        assert "邊數: 2" in out

    def test_l4_kind_distribution_ignores_non_active(self, tmp_path):
        _setup_multi_notebook(tmp_path)
        out = _run(str(tmp_path), "user1", "4").stdout
        assert "synonym" in out
        assert "(100%)" in out
        assert "   2 (" in out or " 2 (100%)" in out

    def test_l1_legacy_db_without_notebook_column(self, tmp_path):
        """舊 DB 無 notebook_id 欄 → L5 退回全部 active，不報錯。"""
        _setup_user(tmp_path, "user1")
        import json

        import numpy as np

        udir = tmp_path / "users" / "user1"
        sqlite3.connect(str(udir / "cards.db")).execute(
            "INSERT INTO card VALUES ('c2', 'b', 'x', 0)"
        ).connection.commit()
        (udir / "card_ids_default.json").write_text(json.dumps(["c1", "c2"]))
        np.save(str(udir / "embeddings_default.npy"), np.eye(2, 4))
        r = _run(str(tmp_path), "user1", "5")
        assert r.returncode == 0, r.stderr
        assert "2/2 active cards (100%)" in r.stdout

    def test_l5_reports_each_notebook_coverage(self, tmp_path):
        _setup_multi_notebook(tmp_path)
        out = _run(str(tmp_path), "user1", "5").stdout
        assert "[work notebook]" in out
        assert "1/1 active cards (100%)" in out

    def test_l6_missing_embedding_in_second_notebook(self, tmp_path):
        import json

        udir = _setup_multi_notebook(tmp_path)
        (udir / "card_ids_work.json").write_text(json.dumps([]))
        out = _run(str(tmp_path), "user1", "6").stdout
        assert "1 張 active 卡片缺 embedding (work notebook)" in out
