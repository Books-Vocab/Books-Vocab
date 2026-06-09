from __future__ import annotations

from .ops_edit_support import *  # noqa: F403

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
