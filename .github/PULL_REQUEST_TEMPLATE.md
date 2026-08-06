<!-- 給 reviewer 與未來 agent 一份「動到什麼 → 該同步什麼 doc」清單。
     不勾 = 該 PR 沒動到該類介面;不要刪 checkbox。 -->

## Summary

<!-- 1-3 句 changelog,寫「why」不是「what」。 -->

## Doc-Sync(動 user/agent-facing 介面必須同步 doc,違反 = 任務沒閉環)

- [ ] **動到 backend router / endpoint / admin endpoint** → 同 PR 更新 `docs/reference/tech_index.md` §Routers
- [ ] **動到 SQLite table / schema** → 同 PR 更新 `docs/reference/tech_index.md` §Log Stores + migration 加入 `cmd_migrate`
- [ ] **新增 / 改名 / 刪除 env var** → 同 PR 更新 `docs/sop/deploy.md` §env(LLM / Sentry / Quota 對應段)+ `docs/reference/tech_index.md` §Environment Variables
- [ ] **動到 `ops_*.py` / `*_cli.py` / CLI subcommand / `devops.sh` 子指令** → 同 PR 更新 `docs/reference/tech_index.md` §Ops 腳本 + `.claude/skills/devops/SKILL.md`(SoT)
- [ ] **新增 user-facing feature**(iOS / backend / admin / chrome) → 同 PR 在 `docs/reference/product_surface.md` 對應段追加 bullet
- [ ] **iOS feature 重構**(改檔名 / 移檔 / 分層) → 同 PR 更新對應 `docs/reference/feature_boundary/<reader|vocabulary|notebook|bookshelf|podcast|settings>.md`
- [ ] **改 sync 狀態流轉** → 同 PR 更新 `docs/reference/sync_lifecycle.md`(SoT)
- [ ] **改 CSV / Card schema 欄位** → 同 PR 更新 `docs/reference/card_format.md`(SoT)
- [ ] **改 host / port / container / Caddy 路由** → 同 PR 更新 `docs/reference/host_topology.md`(SoT)
- [ ] **改生產禁用指令 / preflight / rollback policy** → 同 PR 更新 `docs/policy/safety.md`(SoT)+ 鐵律 7
- [ ] **iOS 大規模重構** → 合併後執行 `ops/gen_ios_baseline.sh --write` 再生 `docs/snapshot/ios_baseline.md`

## 驗證

- [ ] 跑過對應測試(backend `pytest` / iOS `ios_build.sh` / Chrome ext 等),貼上 Exit 0 證據
- [ ] 跑過 `ops/docs_lint.sh` 日常 gate,registry + 本次 changed docs 無 ERROR,且已檢視 registry impact hints

## Notes

<!-- 可留空。reviewer 可參考的特殊背景、已知限制、後續 follow-up。 -->
