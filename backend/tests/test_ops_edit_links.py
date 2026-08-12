# ruff: noqa: F401, F403, F405, I001
"""test ops edit links.py test ownership shard."""



from _ops_edit_support import *  # noqa: F403



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

    @pytest.mark.parametrize("cascade", [False, True], ids=["plain", "cascade"])
    def test_notebook_delete_active_verify_reports_dangling_config(self, tmp_path, cascade):
        uid = _mk_user(tmp_path)
        nb_id = _mk_notebook(tmp_path, uid, "ActiveToDelete")
        if cascade:
            assert _edit(
                str(tmp_path), "card-add", uid, "c1", "--meaning", "m",
                "--notebook", nb_id, "--commit",
            ).returncode == 0
        assert _edit(
            str(tmp_path), "user-config-set", uid, "--active-notebook", nb_id,
            "--commit",
        ).returncode == 0

        command = ["notebook-delete", uid, nb_id]
        if cascade:
            command.append("--cascade")
        r = _edit(str(tmp_path), *command, "--commit", "--json")

        assert r.returncode == 1, r.stderr
        verified = json.loads(r.stdout)["verified"]
        assert verified["ok"] is False
        assert any(
            f"vocab_ui.active_notebook_id={nb_id}" in message
            for message in verified["dangling_config"]
        )

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
