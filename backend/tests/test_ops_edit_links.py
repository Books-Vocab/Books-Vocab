# ruff: noqa: F401, F403, F405, I001
"""test ops edit links.py test ownership shard."""

import time

from _ops_edit_support import *  # noqa: F403


class TestLinkPersistence:
    def test_link_add_persists_to_disk(self, tmp_path):
        uid = _mk_user(tmp_path)
        for w in ("x", "y"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--commit").returncode == 0
        r = _edit(
            str(tmp_path),
            "link-add",
            uid,
            "x",
            "y",
            "--kind",
            "contrasts_with",
            "--confidence",
            "0.9",
            "--reason",
            "r",
            "--commit",
            "--json",
        )
        assert r.returncode == 0, r.stderr
        lid = json.loads(r.stdout)["result"]["link"]["id"]
        # verify 報綠，磁碟必須真有這條 link。
        assert lid in {lk["id"] for lk in _graph_links(tmp_path, uid)}

    def test_link_add_idempotent_flagged(self, tmp_path):
        uid = _mk_user(tmp_path)
        for w in ("p", "q"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--commit").returncode == 0
        common = ("link-add", uid, "p", "q", "--kind", "shares_usage", "--confidence", "0.5", "--reason", "r")
        assert _edit(str(tmp_path), *common, "--commit").returncode == 0
        r = _edit(str(tmp_path), *common, "--commit", "--json")
        assert r.returncode == 0, r.stderr
        # 撞既有 link 應顯式標記，不靜默假裝新建。
        assert json.loads(r.stdout)["result"].get("idempotent") is True

    def test_link_add_can_explicitly_update_existing(self, tmp_path):
        uid = _mk_user(tmp_path)
        for w in ("p2", "q2"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--commit").returncode == 0
        assert (
            _edit(
                str(tmp_path),
                "link-add",
                uid,
                "p2",
                "q2",
                "--kind",
                "shares_usage",
                "--confidence",
                "0.5",
                "--reason",
                "r1",
                "--commit",
                "--json",
            ).returncode
            == 0
        )
        r = _edit(
            str(tmp_path),
            "link-add",
            uid,
            "p2",
            "q2",
            "--kind",
            "contrasts_with",
            "--confidence",
            "0.95",
            "--reason",
            "r2",
            "--if-exists",
            "update",
            "--commit",
            "--json",
        )
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)["result"]
        assert out["existing_semantics"] == "updated-existing"
        p2 = _card_by_content(tmp_path, uid, "p2")
        q2 = _card_by_content(tmp_path, uid, "q2")
        assert p2 is not None and q2 is not None
        link = next(lk for lk in _graph_links(tmp_path, uid) if {lk["from_id"], lk["to_id"]} == {p2["id"], q2["id"]})
        assert abs(link["confidence"] - 0.95) < 1e-6


class TestNewCommands:
    def test_notebook_update_renames(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "OldName")
        r = _edit(str(tmp_path), "notebook-update", uid, nb_id, "--name", "NewName", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        names = [n["name"] for n in _notebook_rows(tmp_path, uid)]
        assert "NewName" in names and "OldName" not in names

    def test_notebook_delete_soft(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "ToDelete")
        r = _edit(str(tmp_path), "notebook-delete", uid, nb_id, "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert "ToDelete" not in [n["name"] for n in _notebook_rows(tmp_path, uid)]

    @pytest.mark.parametrize("cascade", [False, True], ids=["plain", "cascade"])
    def test_notebook_delete_active_verify_reports_dangling_config(self, tmp_path, cascade):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "ActiveToDelete")
        if cascade:
            assert (
                _edit(
                    str(tmp_path),
                    "card-add",
                    uid,
                    "c1",
                    "--meaning",
                    "m",
                    "--notebook",
                    nb_id,
                    "--commit",
                ).returncode
                == 0
            )
        assert (
            _edit(
                str(tmp_path),
                "user-config-set",
                uid,
                "--active-notebook",
                nb_id,
                "--commit",
            ).returncode
            == 0
        )

        command = ["notebook-delete", uid, nb_id]
        if cascade:
            command.append("--cascade")
        r = _edit(str(tmp_path), *command, "--commit", "--json")

        assert r.returncode == 1, r.stderr
        verified = json.loads(r.stdout)["verified"]
        assert verified["ok"] is False
        assert any(f"vocab_ui.active_notebook_id={nb_id}" in message for message in verified["dangling_config"])

    def test_notebook_delete_rejects_default(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _edit(str(tmp_path), "notebook-delete", uid, "default", "--commit", "--json")
        assert r.returncode != 0

    def test_card_move_to_notebook(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "Target")
        assert _edit(str(tmp_path), "card-add", uid, "mover", "--meaning", "m", "--commit").returncode == 0
        r = _edit(str(tmp_path), "card-move", uid, "mover", "--to-notebook", "Target", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert _card_by_content(tmp_path, uid, "mover")["notebook_id"] == nb_id

    def test_card_move_rejects_unknown_notebook(self, tmp_path):
        uid = _mk_user(tmp_path)
        assert _edit(str(tmp_path), "card-add", uid, "stay", "--meaning", "m", "--commit").returncode == 0
        r = _edit(str(tmp_path), "card-move", uid, "stay", "--to-notebook", "Ghost", "--commit", "--json")
        assert r.returncode != 0
        assert _card_by_content(tmp_path, uid, "stay")["notebook_id"] == "default"

    def test_link_update_changes_confidence(self, tmp_path):
        uid = _mk_user(tmp_path)
        for w in ("m", "n"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "x", "--commit").returncode == 0
        r = _edit(
            str(tmp_path),
            "link-add",
            uid,
            "m",
            "n",
            "--kind",
            "shares_usage",
            "--confidence",
            "0.3",
            "--reason",
            "orig",
            "--commit",
            "--json",
        )
        lid = json.loads(r.stdout)["result"]["link"]["id"]
        r2 = _edit(
            str(tmp_path), "link-update", uid, lid, "--confidence", "0.95", "--reason", "revised", "--commit", "--json"
        )
        assert r2.returncode == 0, r2.stderr
        lk = next(lk for lk in _graph_links(tmp_path, uid) if lk["id"] == lid)
        assert abs(lk["confidence"] - 0.95) < 1e-6
        assert lk["reason"] == "revised"


class TestDryRunNoSideEffects:
    def test_card_add_dry_run_writes_nothing(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = _edit(str(tmp_path), "card-add", uid, "phantom", "--meaning", "m", "--json")
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["committed"] is False
        assert _card_by_content(tmp_path, uid, "phantom") is None


class TestLinkSameNotebook:
    """link 嚴格 per-notebook:跨本連結被擋 + card-move 硬刪跨本 link。"""

    def test_link_add_cross_notebook_rejected_with_hint(self, tmp_path):
        uid = _mk_user(tmp_path)
        _mk_notebook(tmp_path, uid, "BookA")
        _mk_notebook(tmp_path, uid, "BookB")
        assert (
            _edit(
                str(tmp_path), "card-add", uid, "alpha", "--meaning", "a", "--notebook", "BookA", "--commit"
            ).returncode
            == 0
        )
        assert (
            _edit(
                str(tmp_path), "card-add", uid, "beta", "--meaning", "b", "--notebook", "BookB", "--commit"
            ).returncode
            == 0
        )
        # alpha 在 BookA、beta 在 BookB,在 BookA 內連 → beta 不在本本 → 擋 + 提示在哪本
        r = _edit(
            str(tmp_path),
            "link-add",
            uid,
            "alpha",
            "beta",
            "--kind",
            "shares_usage",
            "--confidence",
            "0.5",
            "--reason",
            "r",
            "--notebook",
            "BookA",
            "--commit",
            "--json",
        )
        assert r.returncode != 0
        assert "notebook" in (r.stdout + r.stderr).lower()

    def test_card_move_purges_cross_notebook_links(self, tmp_path):
        uid = _mk_user(tmp_path)
        _mk_notebook(tmp_path, uid, "Src")
        _mk_notebook(tmp_path, uid, "Dst")
        for w in ("ml", "nl"):
            assert (
                _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--notebook", "Src", "--commit").returncode
                == 0
            )
        assert (
            _edit(
                str(tmp_path),
                "link-add",
                uid,
                "ml",
                "nl",
                "--kind",
                "shares_usage",
                "--confidence",
                "0.7",
                "--reason",
                "r",
                "--notebook",
                "Src",
                "--commit",
                "--json",
            ).returncode
            == 0
        )
        src_id = next(n["id"] for n in _notebook_rows(tmp_path, uid) if n["name"] == "Src")
        assert len(_graph_links(tmp_path, uid, src_id)) == 1
        # 搬 ml 到 Dst → 原 Src graph 的跨本 link 應被硬刪(維持「無跨本 link」不變量)
        rm = _edit(str(tmp_path), "card-move", uid, "ml", "--to-notebook", "Dst", "--commit", "--json")
        assert rm.returncode == 0, rm.stderr
        assert json.loads(rm.stdout)["result"]["purged_count"] == 1
        assert len(_graph_links(tmp_path, uid, src_id)) == 0

    def test_card_move_dry_run_previews_purge_and_writes_nothing(self, tmp_path):
        """#2706:dry-run 列出將硬刪的 link,且不動資料。"""
        uid = _mk_user(tmp_path)
        _mk_notebook(tmp_path, uid, "Src")
        _mk_notebook(tmp_path, uid, "Dst")
        for w in ("ml", "nl"):
            assert (
                _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--notebook", "Src", "--commit").returncode
                == 0
            )
        link_args = ("link-add", uid, "ml", "nl", "--kind", "shares_usage", "--confidence", "0.7")
        r = _edit(str(tmp_path), *link_args, "--reason", "r", "--notebook", "Src", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        src_id = next(n["id"] for n in _notebook_rows(tmp_path, uid) if n["name"] == "Src")
        link_id = _graph_links(tmp_path, uid, src_id)[0]["id"]

        rd = _edit(str(tmp_path), "card-move", uid, "ml", "--to-notebook", "Dst", "--json")
        assert rd.returncode == 0, rd.stderr
        plan = json.loads(rd.stdout)["plan"]
        assert plan["purge_link_ids"] == [link_id]
        assert plan["purge_count"] == 1
        assert len(_graph_links(tmp_path, uid, src_id)) == 1
        assert _card_by_content(tmp_path, uid, "ml")["notebook_id"] == src_id

    def test_card_move_dry_run_does_not_touch_disk_even_with_legacy_graph(self, tmp_path):
        """#2706 CR P2:dry-run 掃 link 不可觸發 legacy graph.json 遷移,目錄與 mtime 皆不變。"""
        uid = _mk_user(tmp_path)
        _mk_notebook(tmp_path, uid, "Dst")
        for w in ("ml", "nl"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--commit").returncode == 0
        link_args = ("link-add", uid, "ml", "nl", "--kind", "shares_usage", "--confidence", "0.7")
        assert _edit(str(tmp_path), *link_args, "--reason", "r", "--commit").returncode == 0
        ud = _user_dir(tmp_path, uid)
        link_id = _graph_links(tmp_path, uid)[0]["id"]

        def snapshot():
            # sqlite 的 -wal/-shm 是連線開關時的 housekeeping,不是資料寫入,不納入比對
            return {
                p.name: (p.stat().st_mtime_ns, p.stat().st_size)
                for p in ud.iterdir()
                if not p.name.endswith(("-wal", "-shm"))
            }

        for legacy in (False, True):
            if legacy:  # 還原成 pre-migration 佈局:只有 graph.json
                (ud / "graph_default.json").rename(ud / "graph.json")
            before = snapshot()
            rd = _edit(str(tmp_path), "card-move", uid, "ml", "--to-notebook", "Dst", "--json")
            assert rd.returncode == 0, rd.stderr
            assert json.loads(rd.stdout)["plan"]["purge_link_ids"] == [link_id]
            assert snapshot() == before
        assert (ud / "graph.json").exists() and not (ud / "graph_default.json").exists()

    def _preview_vs_commit(self, tmp_path, graph_payload):
        """寫入手工 graph 檔,回傳 (dry-run 預覽的 purge ids, commit 實際 purged ids)。"""
        uid = _mk_user(tmp_path)
        _mk_notebook(tmp_path, uid, "Dst")
        for w in ("ml", "nl"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--commit").returncode == 0
        ml, nl = _card_by_content(tmp_path, uid, "ml")["id"], _card_by_content(tmp_path, uid, "nl")["id"]

        def row(lid, a, b):
            return {"id": lid, "from_id": a, "to_id": b, "kind": "shares_usage", "confidence": 0.5, "reason": "r"}

        (_user_dir(tmp_path, uid) / "graph_default.json").write_text(json.dumps(graph_payload(row, ml, nl)))
        rd = _edit(str(tmp_path), "card-move", uid, "ml", "--to-notebook", "Dst", "--json")
        assert rd.returncode == 0, rd.stderr
        preview = json.loads(rd.stdout)["plan"]["purge_link_ids"]
        rc = _edit(str(tmp_path), "card-move", uid, "ml", "--to-notebook", "Dst", "--commit", "--json")
        assert rc.returncode == 0, rc.stderr
        return preview, json.loads(rc.stdout)["result"]["purged_links"]

    def test_card_move_dry_run_preview_dedupes_duplicate_pair_like_commit(self, tmp_path):
        """#2706 CR:同 pair 兩條 active → store 載入只留第一條,預覽必須相同。"""
        preview, purged = self._preview_vs_commit(tmp_path, lambda row, ml, nl: [row("l1", ml, nl), row("l2", nl, ml)])
        assert purged == ["l1"]
        assert preview == purged

    def test_card_move_dry_run_preview_ignores_dict_format_like_commit(self, tmp_path):
        """#2706 CR:store 只認 list 格式;dict 檔載入為空,預覽不得列出其中的 link。"""
        preview, purged = self._preview_vs_commit(tmp_path, lambda row, ml, nl: {"l9": row("l9", ml, nl)})
        assert purged == []
        assert preview == purged

    @pytest.mark.parametrize(
        "bad_row",
        [
            lambda ml, nl: {
                "id": "b1",
                "from_id": ml,
                "to_id": nl,
                "kind": "no_such_kind",
                "confidence": 0.5,
                "reason": "r",
            },
            lambda ml, nl: {"id": "b2", "to_id": nl, "status": "rejected"},
        ],
        ids=["unknown-kind", "rejected-without-from_id"],
    )
    def test_card_move_dry_run_fails_like_commit_on_invalid_link_row(self, tmp_path, bad_row):
        """#2706 CR P2:store 載入遇壞 row 會拋錯;dry-run 必須同樣失敗,不可綠燈放行到 commit 半途崩潰。"""
        uid = _mk_user(tmp_path)
        _mk_notebook(tmp_path, uid, "Dst")
        for w in ("ml", "nl"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--commit").returncode == 0
        ml, nl = _card_by_content(tmp_path, uid, "ml")["id"], _card_by_content(tmp_path, uid, "nl")["id"]
        (_user_dir(tmp_path, uid) / "graph_default.json").write_text(json.dumps([bad_row(ml, nl)]))
        src_nb = _card_by_content(tmp_path, uid, "ml")["notebook_id"]

        rd = _edit(str(tmp_path), "card-move", uid, "ml", "--to-notebook", "Dst", "--json")
        assert rd.returncode != 0
        assert "link row" in (rd.stdout + rd.stderr)

        rc = _edit(str(tmp_path), "card-move", uid, "ml", "--to-notebook", "Dst", "--commit", "--json")
        assert rc.returncode != 0
        assert _card_by_content(tmp_path, uid, "ml")["notebook_id"] == src_nb

    @pytest.mark.parametrize("attempt", range(6))
    def test_card_move_commit_validates_all_graphs_before_any_purge(self, tmp_path, attempt):
        """#2898:apply_fn 依 set 順序逐本硬刪 link;若後面某本 graph 含壞 row,前面已刪的本不可被先行破壞。

        set 迭代順序為 hash 隨機,故 attempt 重複 6 次以覆蓋「壞本先/後」兩種順序。
        修正後必須在第一次 hard delete 前先開啟並驗證所有 graph,壞 row 時零刪除。
        """
        uid = _mk_user(tmp_path)
        _mk_notebook(tmp_path, uid, "Dst")
        bad_nb = _mk_notebook(tmp_path, uid, "Bad")
        for w in ("ml", "nl"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--commit").returncode == 0
        ml, nl = _card_by_content(tmp_path, uid, "ml")["id"], _card_by_content(tmp_path, uid, "nl")["id"]
        good_row = {"id": "ok1", "from_id": ml, "to_id": nl, "kind": "shares_usage", "confidence": 0.7, "reason": "r"}
        bad_row = {"id": "b1", "from_id": ml, "to_id": nl, "kind": "no_such_kind", "confidence": 0.5, "reason": "r"}
        (_user_dir(tmp_path, uid) / "graph_default.json").write_text(json.dumps([good_row]))
        (_user_dir(tmp_path, uid) / f"graph_{bad_nb}.json").write_text(json.dumps([bad_row]))
        src_nb = _card_by_content(tmp_path, uid, "ml")["notebook_id"]

        rc = _edit(str(tmp_path), "card-move", uid, "ml", "--to-notebook", "Dst", "--commit", "--json")
        assert rc.returncode != 0
        assert _card_by_content(tmp_path, uid, "ml")["notebook_id"] == src_nb
        assert [r["id"] for r in _graph_links(tmp_path, uid, "default")] == ["ok1"]


class TestNotebookDeleteCascade:
    def test_rejects_nonempty_without_cascade(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "Full")
        assert (
            _edit(str(tmp_path), "card-add", uid, "c1", "--meaning", "m", "--notebook", "Full", "--commit").returncode
            == 0
        )
        r = _edit(str(tmp_path), "notebook-delete", uid, nb_id, "--commit", "--json")
        assert r.returncode != 0  # 非空拒絕,避免孤兒卡
        assert "Full" in [n["name"] for n in _notebook_rows(tmp_path, uid)]

    def test_cascade_soft_deletes_cards(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "Full")
        assert (
            _edit(str(tmp_path), "card-add", uid, "c1", "--meaning", "m", "--notebook", "Full", "--commit").returncode
            == 0
        )
        r = _edit(str(tmp_path), "notebook-delete", uid, nb_id, "--cascade", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert "Full" not in [n["name"] for n in _notebook_rows(tmp_path, uid)]
        assert _card_by_content(tmp_path, uid, "c1") is None  # 卡一併軟刪,無孤兒


class TestResolverIdPriority:
    def test_id_takes_priority_over_name(self, tmp_path):
        uid = _mk_user(tmp_path)
        id_a = _mk_notebook(tmp_path, uid, "BookA")
        # 建一本 name 恰好等於 BookA 的 hex id → 傳該字串應解析到 id 那本(非 name 那本)
        _mk_notebook(tmp_path, uid, id_a)
        assert (
            _edit(str(tmp_path), "card-add", uid, "x", "--meaning", "m", "--notebook", id_a, "--commit").returncode == 0
        )
        assert _card_by_content(tmp_path, uid, "x")["notebook_id"] == id_a


class TestSeedFourthRound:
    def _seed(self, tmp_path, uid, spec, *extra):
        p = tmp_path / "spec.json"
        p.write_text(json.dumps(spec))
        return _edit(str(tmp_path), "seed", uid, str(p), *extra)

    def test_dry_run_prevalidates_kind(self, tmp_path):
        uid = _mk_user(tmp_path)
        # 非法 kind dry-run(不帶 --commit)也應提前報錯,不必等 commit 才爆
        r = self._seed(
            tmp_path,
            uid,
            {
                "cards": [{"content": "a", "meaning": "m"}, {"content": "b", "meaning": "m"}],
                "links": [{"from": "a", "to": "b", "kind": "BOGUS", "confidence": 0.5, "reason": "r"}],
            },
            "--json",
        )
        assert r.returncode != 0

    def test_cross_notebook_same_content_verify_ok(self, tmp_path):
        uid = _mk_user(tmp_path)
        # 兩本各一張同 content 不同 meaning → 都正確建好,verify 不該 false-positive
        r = self._seed(
            tmp_path,
            uid,
            {
                "notebooks": [{"name": "A"}, {"name": "B"}],
                "cards": [
                    {"content": "same", "meaning": "defA", "notebook": "A"},
                    {"content": "same", "meaning": "defB", "notebook": "B"},
                ],
            },
            "--commit",
            "--json",
        )
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["verified"]["ok"] is True

    def test_clears_empty_examples_on_rerun(self, tmp_path):
        uid = _mk_user(tmp_path)
        self._seed(tmp_path, uid, {"cards": [{"content": "w", "meaning": "m", "examples": ["ex1", "ex2"]}]}, "--commit")
        assert _card_field(tmp_path, uid, "w", "examples") == ["ex1", "ex2"]
        # 第二次明確設 examples=[] → 清空(區分省略 vs 明確設空)
        self._seed(tmp_path, uid, {"cards": [{"content": "w", "meaning": "m", "examples": []}]}, "--commit")
        assert _card_field(tmp_path, uid, "w", "examples") == []

    def test_review_anchor_makes_review_timestamps_deterministic(self, tmp_path):
        uid = _mk_user(tmp_path)
        spec = {
            "review_anchor": "2026-06-06T00:00:00Z",
            "cards": [
                {"content": "due", "meaning": "m", "review": {"state": "due", "interval": 24}},
                {"content": "reviewed", "meaning": "m", "review": {"state": "reviewed", "interval": 48}},
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
        r = self._seed(
            tmp_path,
            uid,
            {
                "review_anchor": "2026-06-06T00:00:00Z",
                "cards": [
                    {
                        "content": "local",
                        "meaning": "m",
                        "review": {"state": "reviewed", "interval": 24, "anchor": "2026-06-10T12:00:00Z"},
                    },
                ],
            },
            "--commit",
            "--json",
        )
        assert r.returncode == 0, r.stderr
        row = _card_by_content(tmp_path, uid, "local")
        assert row["last_reviewed_at"].startswith("2026-06-10 12:00:00")
        assert row["next_review_at"].startswith("2026-06-11 12:00:00")

    def test_seed_can_write_source_context(self, tmp_path):
        uid = _mk_user(tmp_path)
        r = self._seed(
            tmp_path,
            uid,
            {
                "cards": [
                    {
                        "content": "w",
                        "meaning": "m",
                        "source": {"type": "book", "title": "Demo Book", "chapter": "Chapter 1"},
                    }
                ],
            },
            "--commit",
            "--json",
        )
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
        assert _edit(str(tmp_path), "card-add", uid, "w", "--meaning", "m", "--commit").returncode == 0
        r = _edit(
            str(tmp_path), "card-set-review", uid, "w", "--state", "reviewed", "--interval", "-5", "--commit", "--json"
        )
        assert r.returncode != 0
        assert "間隔" in (r.stdout + r.stderr) or "> 0" in (r.stdout + r.stderr)


class TestLinkListAndMoveAlias:
    def test_link_list_returns_ids(self, tmp_path):
        uid = _mk_user(tmp_path)
        for w in ("p", "q"):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--commit").returncode == 0
        ra = _edit(
            str(tmp_path),
            "link-add",
            uid,
            "p",
            "q",
            "--kind",
            "shares_usage",
            "--confidence",
            "0.6",
            "--reason",
            "r",
            "--commit",
            "--json",
        )
        lid = json.loads(ra.stdout)["result"]["link"]["id"]
        r = _edit(str(tmp_path), "link-list", uid, "--json")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["count"] == 1 and d["links"][0]["id"] == lid
        assert {d["links"][0]["from"], d["links"][0]["to"]} == {"p", "q"}

    def test_card_move_notebook_alias(self, tmp_path):
        uid = _mk_user(tmp_path)
        dst = _mk_notebook(tmp_path, uid, "Dest")
        assert _edit(str(tmp_path), "card-add", uid, "mv", "--meaning", "m", "--commit").returncode == 0
        # 用 --notebook(alias)而非 --to-notebook
        r = _edit(str(tmp_path), "card-move", uid, "mv", "--notebook", "Dest", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        assert _card_by_content(tmp_path, uid, "mv")["notebook_id"] == dst


class TestMarketingSurfaceShaping:
    def test_notebook_update_can_set_sort_order(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "Marketing")
        r = _edit(str(tmp_path), "notebook-update", uid, nb_id, "--sort-order", "-10", "--commit", "--json")
        assert r.returncode == 0, r.stderr
        notebook = next(nb for nb in _notebook_rows(tmp_path, uid) if nb["id"] == nb_id)
        assert notebook["sort_order"] == -10

    def test_user_config_set_can_shape_settings_surface(self, tmp_path):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "Promo Focus")
        r = _edit(
            str(tmp_path),
            "user-config-set",
            uid,
            "--translation-source",
            "en",
            "--translation-target",
            "ja",
            "--review-clock",
            "paused",
            "--paused-at",
            "2026-06-07T09:30:00Z",
            "--review-mode",
            "custom",
            "--custom-initial-interval-hours",
            "18",
            "--custom-remembered-multiplier",
            "2.1",
            "--custom-forgot-multiplier",
            "0.4",
            "--custom-minimum-interval-hours",
            "8",
            "--custom-maximum-interval-hours",
            "720",
            "--active-notebook",
            "Promo Focus",
            "--commit",
            "--json",
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
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--commit").returncode == 0
        ra = _edit(
            str(tmp_path),
            "link-add",
            uid,
            "a",
            "b",
            "--kind",
            "shares_usage",
            "--confidence",
            "0.5",
            "--reason",
            "r",
            "--commit",
            "--json",
        )
        assert ra.returncode == 0, ra.stderr
        lid = json.loads(ra.stdout)["result"]["link"]["id"]
        assert any(lk["id"] == lid for lk in _graph_links(tmp_path, uid))

        rd = _edit(str(tmp_path), "link-delete", uid, lid, "--commit", "--json")
        assert rd.returncode == 0, rd.stderr
        assert not any(lk["id"] == lid for lk in _graph_links(tmp_path, uid))

    def test_link_delete_rejects_missing_link(self, tmp_path):
        uid = _mk_user(tmp_path)
        fake_lid = "link-does-not-exist-1234"
        rd = _edit(str(tmp_path), "link-delete", uid, fake_lid, "--commit", "--json")
        assert rd.returncode != 0
        assert "link" in (rd.stdout + rd.stderr).lower()


class TestLinkUpdateErrors:
    def test_link_update_rejects_missing_link(self, tmp_path):
        uid = _mk_user(tmp_path)
        fake_lid = "link-does-not-exist-5678"
        ru = _edit(str(tmp_path), "link-update", uid, fake_lid, "--confidence", "0.9", "--commit", "--json")
        assert ru.returncode != 0
        assert "link" in (ru.stdout + ru.stderr).lower()


class TestLinkOpsTouchEndpoints:
    """ops-edit 改 link 必須 bump 兩端 card 的 updated_at,否則 iOS 增量 pull 看不到。"""

    @staticmethod
    def _mk_pair(tmp_path, uid, a, b):
        for w in (a, b):
            assert _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--commit").returncode == 0

    @staticmethod
    def _stamps(tmp_path, uid, a, b):
        return (_card_field(tmp_path, uid, a, "updated_at"), _card_field(tmp_path, uid, b, "updated_at"))

    def _add(self, tmp_path, uid, a, b, *extra):
        return _edit(
            str(tmp_path),
            "link-add",
            uid,
            a,
            b,
            "--kind",
            "shares_usage",
            "--confidence",
            "0.5",
            "--reason",
            "r",
            *extra,
            "--json",
        )

    def test_link_add_touches_both_endpoints_only_on_commit(self, tmp_path):
        uid = _mk_user(tmp_path)
        self._mk_pair(tmp_path, uid, "ta", "tb")
        before = self._stamps(tmp_path, uid, "ta", "tb")
        time.sleep(0.01)
        assert self._add(tmp_path, uid, "ta", "tb").returncode == 0  # dry run
        assert self._stamps(tmp_path, uid, "ta", "tb") == before
        assert self._add(tmp_path, uid, "ta", "tb", "--commit").returncode == 0
        after = self._stamps(tmp_path, uid, "ta", "tb")
        assert after[0] > before[0] and after[1] > before[1]
        # idempotent keep:什麼都沒變 → 不 touch
        time.sleep(0.01)
        assert self._add(tmp_path, uid, "ta", "tb", "--commit").returncode == 0
        assert self._stamps(tmp_path, uid, "ta", "tb") == after

    def test_link_update_and_delete_touch_both_endpoints(self, tmp_path):
        uid = _mk_user(tmp_path)
        self._mk_pair(tmp_path, uid, "tc", "td")
        r = self._add(tmp_path, uid, "tc", "td", "--commit")
        lid = json.loads(r.stdout)["result"]["link"]["id"]
        s0 = self._stamps(tmp_path, uid, "tc", "td")
        time.sleep(0.01)
        ru = _edit(str(tmp_path), "link-update", uid, lid, "--confidence", "0.4", "--commit", "--json")
        assert ru.returncode == 0, ru.stderr
        s1 = self._stamps(tmp_path, uid, "tc", "td")
        assert s1[0] > s0[0] and s1[1] > s0[1]
        time.sleep(0.01)
        rd = _edit(str(tmp_path), "link-delete", uid, lid, "--commit", "--json")
        assert rd.returncode == 0, rd.stderr
        s2 = self._stamps(tmp_path, uid, "tc", "td")
        assert s2[0] > s1[0] and s2[1] > s1[1]

    def test_card_move_touches_purged_link_peers(self, tmp_path):
        uid = _mk_user(tmp_path)
        _mk_notebook(tmp_path, uid, "TSrc")
        _mk_notebook(tmp_path, uid, "TDst")
        for w in ("tp", "tq"):
            assert (
                _edit(str(tmp_path), "card-add", uid, w, "--meaning", "m", "--notebook", "TSrc", "--commit").returncode
                == 0
            )
        assert (
            _edit(
                str(tmp_path),
                "link-add",
                uid,
                "tp",
                "tq",
                "--kind",
                "shares_usage",
                "--confidence",
                "0.7",
                "--reason",
                "r",
                "--notebook",
                "TSrc",
                "--commit",
            ).returncode
            == 0
        )
        before = _card_field(tmp_path, uid, "tq", "updated_at")
        time.sleep(0.01)
        rm = _edit(str(tmp_path), "card-move", uid, "tp", "--to-notebook", "TDst", "--commit", "--json")
        assert rm.returncode == 0, rm.stderr
        res = json.loads(rm.stdout)["result"]
        assert res["purged_count"] == 1
        assert res["touched_peers"] == 1
        assert _card_field(tmp_path, uid, "tq", "updated_at") > before
