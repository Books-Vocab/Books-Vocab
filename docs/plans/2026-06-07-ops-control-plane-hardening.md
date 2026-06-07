<!-- doc-meta
tier: reference
authority: derived
update_trigger: planning
scope:
  - ops/
  - docs/
verified_against: 887a248d
-->
# Ops Control Plane Hardening Plan

目標:把 `ops/` 從「可用腳本集合」收斂成 agent 可依賴的控制平面。原則是優先組合官方/既有完整實作,KG 只補統一入口、輸出契約、side-effect gate 與 regression。

## P0 — 讓 ops regression 代表真實綠燈

1. ✅ 修正 `docs-lint` 契約矛盾。
   - 現象:`./ops/test_ops.sh` 會因 `docs-lint` group 失敗;根因是 `ops/tests/test_docs_lint.sh` 要求 `--audit` `WARN: 0`,但 `ops/docs_lint.sh` 的設計是 WARN 不應 fail,除非 `--strict`。
   - 決策:保留 `docs_lint.sh` 的 contract(WARN 不 fail,除非 `--strict`),把 regression 改成驗 `--audit`/`--all` exit 0 + `ERROR: 0`;stale WARN 仍在 audit 輸出中可見。
   - 驗證:`./ops/test_ops.sh docs-lint` 通過。

2. ✅ 測試失敗時自動 dump 對應 out 檔。
   - 現象:部分 shell tests 把 stdout/stderr redirect 到 `/tmp`,失敗只回 rc,agent 需要二次調用才知道原因。
   - 決策:`ops/tests/test_docs_lint.sh` 新增 `run_capture` / `require_grep` / `dump_file`,命令失敗或 pattern 缺失時印最後 80 行與檔案 path。
   - 驗證:`./ops/test_ops.sh` 通過 12 groups / 0 failed。

## P1 — 統一 Python entrypoint 執行環境

1. ✅ 掃全 `ops/*.py` 的 shebang / wrapper。
   - 目標:所有 Python entrypoint 要嘛使用 uv shebang,要嘛由 shell wrapper 以 `uv run --python 3.13` 或專案 venv 呼叫。
   - 決策:裸 `#!/usr/bin/env python3` 全部改為 uv shebang;stdlib 工具固定 `uv run --python 3.13`,backend/numpy 工具走 `--project backend`,S3 podcast 工具明確 `--with boto3`。
   - 驗證:`./ops/test_ops.sh python-entrypoints` 通過;代表性 direct smoke: `ops/data_inspect.py --help` / `ops/podcast_ops.py --help` / `ops/gen_web_tokens.py --help` / `ops/graph_analysis.py --help`。

2. ✅ 擴大 `test_python_entrypoints.sh`。
   - 完成判準:測試掃描全 `ops/*.py` 與 known wrappers,禁止裸 `#!/usr/bin/env python3`,除非明確 allowlist + 理由。
   - 決策:新增三條 regression:全 `ops/*.py` 禁裸 `python3` shebang;可執行 Python entrypoint 必須是 uv shebang;有 shebang 的 Python 工具必須有 executable bit。
   - 驗證:`./ops/test_ops.sh python-entrypoints` 通過。

## P1 — Release-critical surfaces 納入聚合測試

1. ✅ 把 iOS release regression 納入預設聚合。
   - 現況:`ops/test_ios_release.sh` 存在但未被 `test_ops.sh` 預設跑。
   - 決策:`test_ops.sh` 新增預設 group `ios-release`;`ops/test_ios_release.sh` 設為 executable。
   - 完成判準:`./ops/test_ops.sh --list` 有 `ios-release` 或併入 `ios-ops`;預設 `./ops/test_ops.sh` 會覆蓋 `ios_release.sh` help guard / upload gate / value guard。
   - 驗證:`./ops/test_ops.sh ios-release` 通過。

2. ✅ ASC 測試提供明確入口。
   - 現況:`test_asc.sh` 與 `test_asc_text_bundle.py` 是 release-critical,但不在非 ASC 聚合;容易讓「ops 全綠」產生假安全感。
   - 決策:`test_ops.sh` 新增 optional group `asc` 與 `release-surfaces`;預設仍是非 ASC ops regression,避免日常 gate 語意改變。
   - 完成判準:新增 `./ops/test_ops.sh asc` 或 `release-surfaces`,至少跑 ASC shell regression 與 text bundle unit tests;文件明確說是否納入 default。
   - 驗證:`./ops/test_ops.sh asc` 與 `./ops/test_ops.sh release-surfaces` 通過。

## P2 — 縮小 raw remote command 面

1. ✅ 收斂 `status_all.sh` 這類 SSH 旁路。
   - 方向:砍掉,或改成 `devops_kg_safe.sh status/health` 的薄 wrapper。
   - 決策:`status_all.sh` 保留相容入口,但移除 raw SSH / `run_remote`,改為委派 `devops_kg_safe.sh status` + `health`。
   - 完成判準:常用維運查詢都有 typed subcommand;agent 不需呼叫 raw `ssh` / raw `run` 來查基本狀態。
   - 驗證:`./ops/test_ops.sh devops` 通過,並新增 regression 禁止 `status_all.sh` 出現 raw `ssh` / `run_remote`。

2. 持續把高頻 raw `run` 用法轉成 typed subcommand。
   - 原則:`devops_kg_safe.sh` blocklist 是最後防線,不是主要 API。新增 typed subcommand 比擴黑名單更可靠。

## P2 — iOS ops 後續收斂

1. ✅ `ios_test.sh` 改為 `xcresult-first`。
   - 方向:加 `-resultBundlePath`,用 `xcrun xcresulttool get test-results summary/tests` 抽 failing tests / executed count;現有 raw log false-green 防護保留為 fallback。
   - 決策:`ios_diagnostics.py --kind test` 讀官方 test summary/tests;`ios_test.sh` 產出 `Test.xcresult`,第一屏列 `[ios][tests]`,false-green executed count 優先取 `.xcresult`、raw log fallback。
   - 驗證:`./ops/test_ops.sh ios-ops ios-release` 與 `uv run --project backend pytest -q ops/tests/test_ios_diagnostics.py` 通過。

2. ✅ `ios_release.sh` archive 階段接 `.xcresult` diagnostics。
   - 方向:和 `ios_build.sh` 一樣輸出 `[ios][issues] source=xcresult-build-results ...`,讓 archive warning/error 第一屏可見。
   - 決策:archive 階段保存 raw log + `Archive.xcresult`,成功/失敗都跑 `ios_diagnostics.py`;archive 失敗時保留兩個 path。
   - 驗證:`./ops/test_ops.sh ios-ops ios-release` 通過。

3. ✅ `ios_ops.sh doctor` 擴充成完整 release readiness。
   - 檢查 project `MARKETING_VERSION(CURRENT_PROJECT_VERSION)`、Organizer latest、TestFlight latest、ASC version state、Sentry wiring、StoreKit config、signing profile。
   - 決策:doctor 新增 `[ios][readiness]` summary,read-only 覆蓋 project / Organizer / TestFlight / ASC version state / signing / StoreKit / Sentry;ASC state 有短 deadline;TestFlight build number 未增加時標 `status=block`。
   - 驗證:`./ops/ios_ops.sh doctor` 可輸出 project=1.6(4)、Organizer latest=1.6(3)、TestFlight latest=3、ASC 1.6=REJECTED、signing/storekit/sentry ok;`./ops/test_ops.sh ios-ops` 通過。

4. ✅ `ios_ops.sh workflow release` 補發版操作編排。
   - 方向:把「跑 doctor → all-targets test → build → archive → upload → ASC metadata/rejection → GUI submit」變成 read-only workflow output,不要讓 agent 靠 SOP 記憶拼命令。
   - 決策:新增 `[ios][workflow] step=N key=... status=todo|ready|block|warn|manual command="..." note="..."`;submit/resubmit 保持 `manual` 邊界。
   - 驗證:`./ops/ios_ops.sh workflow release` 可輸出 build 4 upload ready、ASC 1.6 REJECTED rejection-resolution todo;`./ops/test_ops.sh ios-ops` 通過。

5. ✅ `ios_ops.sh doctor/workflow` 補機器可讀 JSON contract。
   - 方向:保留人看的第一屏摘要，同時讓 agent/CI 用一次命令取得完整 readiness/workflow 物件，減少重複查詢與文字解析。
   - 決策:`doctor --json` 輸出 `kg.ios.doctor.v1` + `readiness[]`;`workflow release --json` 輸出 `kg.ios.workflow.v1` + `steps[]`。文字與 JSON 共用 readiness 判斷 helper，workflow status 收斂為 `todo|ready|block|warn|manual`，降低 drift。
   - 驗證:`./ops/ios_ops.sh doctor --json | jq ...`、`./ops/ios_ops.sh workflow release --json | jq ...`、`./ops/test_ops.sh ios-ops`。

6. ✅ `ios_ops.sh snapshot/dashboard` 補單次狀態拉取入口。
   - 方向:agent 第一輪要能用一個 read-only command 拉到 project、Organizer、TestFlight、readiness 與 release workflow,不再多次調用 `status`/`doctor`/`workflow` 後自行合併。
   - 決策:`snapshot --json` 輸出 `kg.ios.snapshot.v1`,合併 `doctor --json` 與 `workflow release --json`;`dashboard` 作為 human-readable alias。
   - 驗證:`KG_IOS_OPS_FIXTURE=1 ./ops/ios_ops.sh snapshot --json | jq ...` 與 `./ops/test_ops.sh ios-ops`。

7. ✅ `ios_ops.sh runs/reports` 補最近 build/test 報告入口。
   - 方向:對齊 Xcode Report Navigator,讓 agent 第一輪看到最近 build/test verdict、log、xcresult path 與 artifact 是否仍存在。
   - 決策:`runs --json` 輸出 `kg.ios.runs.v1`,優先讀 `kg_ios_build_verdict.json` / `kg_ios_test_verdict.json`,legacy 單行 verdict 只作 fallback;`snapshot --json` 內嵌同一份 `runs`。
   - 驗證:`TMPDIR=<fixture-with-spaces> ./ops/ios_ops.sh runs --json | jq ...`、missing verdict schema fixture、`snapshot --json` fixture 驗 `.runs`、`./ops/test_ops.sh ios-ops`。

## 驗證矩陣

- `./ops/test_ops.sh docs-lint`
- `./ops/test_ops.sh python-entrypoints`
- `./ops/test_ops.sh ios-ops`
- `./ops/test_ops.sh ios-release` 或等效 release surface group
- `./ops/test_ops.sh asc` 或等效 ASC group
- `./ops/docs_lint.sh --files docs/plans/2026-06-07-ops-control-plane-hardening.md`
