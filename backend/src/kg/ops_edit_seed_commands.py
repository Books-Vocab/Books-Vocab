from __future__ import annotations

from .ops_edit_support import (
    _CLONE_TMP_SUFFIX,
    _VALID_REVIEW_STATES,
    _WORLD_BACKUP_ROOT,
    UTC,
    Any,
    CardReviewState,
    EditContext,
    EditError,
    LinkKind,
    Path,
    ReviewEventStore,
    _assert_clean_notebook_name,
    _card_store,
    _clone_source_files,
    _clone_source_fingerprint,
    _count_active_cards,
    _count_graph_links,
    _count_review_events,
    _graph_store,
    _is_vocab_file,
    _list_world_backups,
    _notebook_store,
    _parse_seed_datetime,
    _read_card_review_states,
    _replace_world_from_snapshot,
    _resolve_card_in_notebook,
    _review_fields,
    _source_to_json,
    _sqlite_online_backup,
    _world_members,
    argparse,
    assert_safe_uid,
    backup_world,
    data_dir,
    datetime,
    emit,
    json,
    shutil,
    synthesize_many,
    tarfile,
    tempfile,
    user_dir_for,
    users_file,
    world_backup_root,
)


# 擴充 review 形式(計數器直設,`ops_cli world-export` 的無損重放面)的合法鍵。
_REVIEW_COUNTER_KEYS = frozenset({
    "review_count", "review_streak", "lapse_count", "review_interval_hours",
    "next_review_at", "last_reviewed_at", "last_review_feedback",
})


def _review_form(rv: Any, label: str) -> str:
    """判定 card review 形式:legacy ``state`` / 擴充 ``counters`` / ``none``。

    兩形式混用 fail-loud —— state 是「語意態 + anchor 推導時間」,counters 是
    「絕對值直設」,混填會產生互相矛盾的欄位來源。
    """
    if not isinstance(rv, dict):
        return "none"
    has_state = rv.get("state") not in (None, "")
    has_counters = any(k in rv for k in _REVIEW_COUNTER_KEYS)
    if has_state and has_counters:
        raise EditError(f"{label} 不可混用 state 形式與計數器形式:{sorted(rv)}")
    if has_counters:
        return "counters"
    if has_state:
        return "state"
    return "none"


def _parse_review_counters(rv: dict[str, Any], label: str) -> dict[str, Any]:
    """擴充 review 形式 → card update 欄位(僅回傳 spec 有宣告的鍵)。

    嚴格白名單鍵(typo fail-loud,對齊 seed 其餘預驗風格);``review_count > 0``
    必須帶 ``last_reviewed_at``:它是 review events 確定式合成的時間錨
    (對齊 `_read_card_review_states` 的合成前提),缺錨的計數器會產出
    iOS heatmap/streak 對不上的半套狀態。
    """
    unknown = set(rv) - _REVIEW_COUNTER_KEYS
    if unknown:
        raise EditError(
            f"{label} 計數器形式含未知鍵 {sorted(unknown)}(允許 {sorted(_REVIEW_COUNTER_KEYS)})"
        )
    out: dict[str, Any] = {}
    for key in ("review_count", "review_streak", "lapse_count"):
        if key in rv:
            val = rv[key]
            if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                raise EditError(f"{label}.{key} 須為 >= 0 整數:{val!r}")
            out[key] = val
    if "last_review_feedback" in rv:
        val = rv["last_review_feedback"]
        if isinstance(val, bool) or val not in (-1, 0, 1):
            raise EditError(f"{label}.last_review_feedback 須為 -1/0/1:{val!r}")
        out["last_review_feedback"] = val
    if "review_interval_hours" in rv:
        val = rv["review_interval_hours"]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or val <= 0:
            raise EditError(f"{label}.review_interval_hours 須為 > 0 數值:{val!r}")
        out["review_interval_hours"] = float(val)
    for key in ("next_review_at", "last_reviewed_at"):
        if key in rv:
            out[key] = _parse_seed_datetime(rv[key], f"{label}.{key}")
    if out.get("review_count", 0) > 0 and out.get("last_reviewed_at") is None:
        raise EditError(f"{label}: review_count > 0 需同時提供 last_reviewed_at(review events 合成錨點)")
    return out


def cmd_seed(args: argparse.Namespace) -> int:
    """一次性把 notebooks + cards + links 整套灌入(mock/demo 帳號用)。

    spec JSON 結構:
      {
        "notebooks": [{"name", "color"?, "cover_pattern"?, "sort_order"?,
                       "is_default"?}],
        "cards": [{"content","meaning","pos"?,"examples"?,"collocations"?,
                   "note"?,"difficulty"?,"mode"?,"root_form"?,"inflections"?,
                   "is_archived"?,"notebook"?,
                   "review"?: {"state":"new|due|reviewed","interval"?}
                            | {review_count/review_streak/lapse_count/
                               review_interval_hours/next_review_at/
                               last_reviewed_at/last_review_feedback}}],
        "links": [{"from","to","kind","confidence","reason","notebook"?}]
      }
    cards/links 的 "notebook" 可指 spec 建立的、或**既存的** notebook name / id;
    links 的 from/to 用 card content 參照(seed 內先建卡再連結)。

    review 兩形式:legacy ``state`` 由 anchor 推導時間(既有消費者不變);擴充
    計數器形式直設絕對值(`world-export` 產物的無損重放),``review_count > 0``
    會經 `synthesize_many` 確定式合成逐筆 review events 寫入 review_events.db
    (uuid5 event_id,重跑經 store 去重而冪等)。``is_default: true`` 的 notebook
    映射到既存預設本(id 恆 "default",改名不增殖),使導出的預設本可重放。
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
        default_entries = 0
        for n in notebooks:
            name = n.get("name") or ""
            _assert_clean_notebook_name(name)
            # spec 內重複 notebook name 會建出多本同名、name→id 映射被後者覆蓋、
            # 前者成孤兒(dogfood A MED-2);寫入前擋掉。
            if name in seen_names:
                raise EditError(f"notebooks 有重複 name:{name!r}")
            seen_names.add(name)
            if "sort_order" in n:
                so = n["sort_order"]
                if isinstance(so, bool) or not isinstance(so, int):
                    raise EditError(f"notebooks[{name!r}].sort_order 須為整數:{so!r}")
            if n.get("is_default"):
                default_entries += 1
        if default_entries > 1:
            # 預設本結構上唯一(id 恆 "default");兩本以上 is_default 是矛盾 spec。
            raise EditError("notebooks 至多一本 is_default: true(預設本唯一)")
        for i, c in enumerate(cards):
            if not (c.get("content") or "").strip():
                raise EditError(f"cards[{i}] content 空白:{c!r}")
            # meaning 空白與 card-import 一致擋掉:demo 卡需有定義(dogfood A MED-1)。
            if not (c.get("meaning") or "").strip():
                raise EditError(f"cards[{i}] meaning 空白:{c.get('content')!r}")
            # review.state 非法值 fail-loud,而非靜默當 reviewed(dogfood B5 / A LOW-1)。
            rv = c.get("review")
            if isinstance(rv, dict):
                form = _review_form(rv, f"cards[{i}].review")
                if form == "counters":
                    _parse_review_counters(rv, f"cards[{i}].review")
                else:
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

    dist = {"new": 0, "due": 0, "reviewed": 0, "counters": 0, "unspecified": 0}
    for c in cards:
        rv = c.get("review")
        if isinstance(rv, dict) and _review_form(rv, "cards[].review") == "counters":
            dist["counters"] += 1
            continue
        st = rv.get("state") if isinstance(rv, dict) else None
        dist[st if st in _VALID_REVIEW_STATES else "unspecified"] += 1
    plan = {
        "notebooks": len(notebooks), "cards": len(cards), "links": len(links),
        "notebook_names": [n.get("name") for n in notebooks],
        "card_sample": [c.get("content") for c in cards[:5]],
        "link_sample": [f'{link.get("from")}→{link.get("to")} ({link.get("kind")})' for link in links[:3]],
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
            if n.get("is_default"):
                # 預設本 id 恆 "default" 且唯一:is_default entry 映到既存預設本
                # (可改名/改欄位,不增殖新本),使 world-export 導出的預設本可無損重放。
                nb_id, reused = "default", True
            elif name in name_to_id:
                nb_id, reused = name_to_id[name], True
            else:
                nb = nb_store.create(name=name, color=n.get("color"),
                                     cover_pattern=n.get("cover_pattern"))
                nb_id, reused = nb.id, False
            # 「確保狀態」語意:spec 宣告的欄位一律 upsert(reuse 者對齊 spec,
            # 新建者冗餘覆蓋無害 —— NotebookStore.update 有 has_changes 檢查)。
            # 用 `key in n` 區分「省略=保留舊值」與「明確 null=清空」,對齊 card 欄位語意。
            nb_updates: dict[str, Any] = {"name": name}
            if "color" in n:
                nb_updates["color"] = n["color"]
            if "cover_pattern" in n:
                nb_updates["cover_pattern"] = n["cover_pattern"]
            if "sort_order" in n:
                nb_updates["sort_order"] = n["sort_order"]
            nb_store.update(nb_id, **nb_updates)
            name_to_id[name] = nb_id
            existing_ids.add(nb_id)
            entry = {"id": nb_id, "name": name}
            if reused:
                entry["reused"] = True
            created_nb.append(entry)

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
        synth_states: list[CardReviewState] = []
        for c in cards:
            nb_id = _resolve_nb(c.get("notebook", "default"))
            card = card_store.add(
                content=c["content"], meaning=c.get("meaning", ""),
                pos=c.get("pos"), examples=c.get("examples") or [],
                collocations=c.get("collocations") or [],
                mode=c.get("mode", "recognition"),
                root_form=c.get("root_form"),
                inflections=c.get("inflections") or [],
                notebook_id=nb_id,
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
            if "root_form" in c:
                updates["root_form"] = c["root_form"]
            if "inflections" in c:
                updates["inflections"] = c["inflections"] or []
            if "is_archived" in c:
                updates["is_archived"] = bool(c["is_archived"])
            if "source" in c:
                updates["source"] = _source_to_json(c.get("source"), "cards[].source")
            rv = c.get("review")
            form = _review_form(rv, "cards[].review")
            if form == "state":
                review_now = _parse_seed_datetime(rv.get("anchor"), "cards[].review.anchor") or now
                updates.update(_review_fields(rv["state"], rv.get("interval"), review_now))
            elif form == "counters":
                counters = _parse_review_counters(rv, "cards[].review")
                updates.update(counters)
                if counters.get("review_count", 0) > 0:
                    # 計數器 ⇒ 逐筆 review events 一併合成(對齊 clone-demo 的合成
                    # 契約),否則 iOS heatmap/streak 與卡片聚合對不上。
                    synth_states.append(CardReviewState(
                        card_id=card.id, content=c["content"], notebook_id=nb_id,
                        review_count=counters["review_count"],
                        lapse_count=counters.get("lapse_count", 0),
                        review_streak=counters.get("review_streak", 0),
                        last_review_feedback=counters.get("last_review_feedback", -1),
                        last_reviewed_at=counters["last_reviewed_at"],
                        created_at=card.created_at,
                        review_interval_hours=counters.get("review_interval_hours", 12.0),
                    ))
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

        # 計數器形式的卡 → 確定式合成逐筆 review events(uuid5 event_id,
        # store 以 event_id 去重 → 重跑冪等,對齊 seed 整體的「確保狀態」語意)。
        events_written = 0
        if synth_states:
            events = synthesize_many(synth_states)
            if events:
                store = ReviewEventStore(ctx.user_dir / "review_events.db")
                try:
                    events_written = store.insert_many(events)["inserted"]
                finally:
                    store.close()

        seed_state["link_errors"] = link_errors
        return {"notebooks_created": created_nb, "cards_added": actually_new,
                "skipped_dup": len(cards) - actually_new,
                "links_added": added_links, "link_errors": link_errors,
                "review_events_written": events_written}

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
