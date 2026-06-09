"""ops_world_expectation.derive_expectation 測試 —— 從 seed/steps 靜態導出 expectation。

核心契約(防 tautology):derive 只讀宣告 spec、絕不讀 DB;diff 的 actual 側走
project_user_world 真讀盤。本測試用「真跑 seed → 真讀 → diff == 0」證明 derive 正確且
非自我確認,並用「動 seed 一欄 → diff 必 FAIL」證明它真的有鑑別力。
"""

import json
from pathlib import Path

from kg.ops_world_diff import diff_world_state
from kg.ops_world_expectation import SPEC_SCHEMA, derive_expectation
from kg.ops_world_projection import project_user_world
from ops_helpers import run_ops_edit as _edit

_SEED = {
    "review_anchor": "2026-06-06T00:00:00Z",
    "notebooks": [
        {"name": "Alpha", "color": "#111111", "cover_pattern": "waves"},
        {"name": "Beta", "color": "#222222", "cover_pattern": "grid"},
    ],
    "cards": [
        {"content": "meticulous", "meaning": "一絲不苟的", "pos": "adj.",
         "notebook": "Alpha", "review": {"state": "reviewed"}},
        {"content": "evoke", "meaning": "喚起", "pos": "v.", "notebook": "Alpha",
         "review": {"state": "new"}},
        {"content": "entropy", "meaning": "熵", "pos": "n.", "notebook": "Beta",
         "review": {"state": "due"}},
    ],
    "links": [
        {"from": "meticulous", "to": "evoke", "kind": "shares_usage",
         "confidence": 0.7, "reason": "x", "notebook": "Alpha"},
    ],
}

_STEPS = [
    {"subcommand": "user-config-set",
     "args": ["--review-clock", "paused", "--paused-at", "2026-06-07T09:30:00Z"]},
]


class TestDeriveStructure:
    def test_schema_and_passthrough_fields(self):
        spec = derive_expectation(_SEED, _STEPS)
        assert spec["schema"] == SPEC_SCHEMA
        nb = {n["name"]: n for n in spec["notebooks"]}
        assert nb["Alpha"]["cover_pattern"] == "waves"
        cards = {c["content"]: c for c in spec["cards"]}
        assert cards["meticulous"]["meaning"] == "一絲不苟的"

    def test_pos_excluded_not_surfaced_by_projection(self):
        # pos 寫進 DB 但 project_user_world._load_cards 不撈 → 導出會 false-fail,故不導。
        spec = derive_expectation(_SEED, _STEPS)
        for c in spec["cards"]:
            assert "pos" not in c

    def test_review_aggregates_excluded(self):
        # review.state → review_count/last_reviewed_at 是 intended transform,
        # 導 raw 會 false-fail、導 computed 是 tautology。一律不導。
        spec = derive_expectation(_SEED, _STEPS)
        for c in spec["cards"]:
            assert "review" not in c
            assert "review_count" not in c
            assert "last_reviewed_at" not in c

    def test_config_review_clock_from_steps(self):
        spec = derive_expectation(_SEED, _STEPS)
        assert spec["config"]["review_clock"]["is_paused"] is True

    def test_graph_links_from_seed(self):
        spec = derive_expectation(_SEED, _STEPS)
        g = {x["notebook"]: x for x in spec["graphs"]}
        link = g["Alpha"]["links"][0]
        assert (link["from"], link["to"], link["kind"]) == (
            "meticulous", "evoke", "shares_usage")


class TestRealParity:
    """真跑 seed → 真讀盤 → diff,證明 derive 與真實落地一致且非 tautology。"""

    def _materialize(self, tmp_path: Path, uid: str = "demo") -> str:
        _edit(str(tmp_path), "user-create", uid, "--commit", "--json")
        seed_path = tmp_path / "seed.json"
        seed_path.write_text(json.dumps(_SEED, ensure_ascii=False), encoding="utf-8")
        r = _edit(str(tmp_path), "seed", uid, str(seed_path), "--commit", "--json")
        assert r.returncode == 0, r.stderr
        for step in _STEPS:
            r = _edit(str(tmp_path), step["subcommand"], uid, *step["args"],
                      "--commit", "--json")
            assert r.returncode == 0, r.stderr
        return uid

    def test_derived_expectation_matches_real_world(self, tmp_path):
        uid = self._materialize(tmp_path)
        expected = derive_expectation(_SEED, _STEPS)
        actual = project_user_world(uid, data_root=tmp_path)
        result = diff_world_state(actual, expected)
        assert result["mismatches"] == [], result["mismatches"]

    def test_derive_has_discriminating_power(self, tmp_path):
        # 動 seed 一個 verbatim 欄位 → 真實落地不變 → diff 必抓到落差。
        uid = self._materialize(tmp_path)
        tampered = json.loads(json.dumps(_SEED))
        tampered["cards"][0]["meaning"] = "WRONG"
        expected = derive_expectation(tampered, _STEPS)
        actual = project_user_world(uid, data_root=tmp_path)
        result = diff_world_state(actual, expected)
        assert result["mismatches"], "derive 無鑑別力:錯誤 meaning 竟未被 diff 抓到"
