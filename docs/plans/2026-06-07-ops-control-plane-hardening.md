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

1. 修正 `docs-lint` 契約矛盾。
   - 現象:`./ops/test_ops.sh` 會因 `docs-lint` group 失敗;根因是 `ops/tests/test_docs_lint.sh` 要求 `--audit` `WARN: 0`,但 `ops/docs_lint.sh` 的設計是 WARN 不應 fail,除非 `--strict`。
   - 決策點:要嘛清掉當前 `docs/sop/doc_sync.md` / `docs/sop/ios.md` stale debt,要嘛把測試改成驗「audit 可報 WARN 但 exit 0」。
   - 完成判準:`./ops/test_ops.sh docs-lint` 穩定通過;測試輸出清楚列出 WARN 是否預期。

2. 測試失敗時自動 dump 對應 out 檔。
   - 現象:部分 shell tests 把 stdout/stderr redirect 到 `/tmp`,失敗只回 rc,agent 需要二次調用才知道原因。
   - 完成判準:每個 `ops/tests/*.sh` 失敗時至少印最後 80 行相關 out/err,並保留 path。

## P1 — 統一 Python entrypoint 執行環境

1. 掃全 `ops/*.py` 的 shebang / wrapper。
   - 目標:所有 Python entrypoint 要嘛使用 uv shebang,要嘛由 shell wrapper 以 `uv run --python 3.13` 或專案 venv 呼叫。
   - 背景:目前只有少數 wrapper 被 `ops/tests/test_python_entrypoints.sh` 守住;旁路 Python 腳本仍可能吃到 Homebrew `python3`。

2. 擴大 `test_python_entrypoints.sh`。
   - 完成判準:測試掃描全 `ops/*.py` 與 known wrappers,禁止裸 `#!/usr/bin/env python3`,除非明確 allowlist + 理由。
   - 驗證:`./ops/test_ops.sh python-entrypoints` 通過。

## P1 — Release-critical surfaces 納入聚合測試

1. 把 iOS release regression 納入預設聚合。
   - 現況:`ops/test_ios_release.sh` 存在但未被 `test_ops.sh` 預設跑。
   - 完成判準:`./ops/test_ops.sh --list` 有 `ios-release` 或併入 `ios-ops`;預設 `./ops/test_ops.sh` 會覆蓋 `ios_release.sh` help guard / upload gate / value guard。

2. ASC 測試提供明確入口。
   - 現況:`test_asc.sh` 與 `test_asc_text_bundle.py` 是 release-critical,但不在非 ASC 聚合;容易讓「ops 全綠」產生假安全感。
   - 完成判準:新增 `./ops/test_ops.sh asc` 或 `release-surfaces`,至少跑 ASC shell regression 與 text bundle unit tests;文件明確說是否納入 default。

## P2 — 縮小 raw remote command 面

1. 收斂 `status_all.sh` 這類 SSH 旁路。
   - 方向:砍掉,或改成 `devops_kg_safe.sh status/health` 的薄 wrapper。
   - 完成判準:常用維運查詢都有 typed subcommand;agent 不需呼叫 raw `ssh` / raw `run` 來查基本狀態。

2. 持續把高頻 raw `run` 用法轉成 typed subcommand。
   - 原則:`devops_kg_safe.sh` blocklist 是最後防線,不是主要 API。新增 typed subcommand 比擴黑名單更可靠。

## P2 — iOS ops 後續收斂

1. `ios_test.sh` 改為 `xcresult-first`。
   - 方向:加 `-resultBundlePath`,用 `xcrun xcresulttool get test-results summary/tests` 抽 failing tests / executed count;現有 raw log false-green 防護保留為 fallback。

2. `ios_release.sh` archive 階段接 `.xcresult` diagnostics。
   - 方向:和 `ios_build.sh` 一樣輸出 `[ios][issues] source=xcresult-build-results ...`,讓 archive warning/error 第一屏可見。

3. `ios_ops.sh doctor` 擴充成完整 release readiness。
   - 檢查 project `MARKETING_VERSION(CURRENT_PROJECT_VERSION)`、Organizer latest、TestFlight latest、ASC version state、Sentry wiring、StoreKit config、signing profile。

## 驗證矩陣

- `./ops/test_ops.sh docs-lint`
- `./ops/test_ops.sh python-entrypoints`
- `./ops/test_ops.sh ios-ops`
- `./ops/test_ops.sh ios-release` 或等效 release surface group
- `./ops/test_ops.sh asc` 或等效 ASC group
- `./ops/docs_lint.sh --files docs/plans/2026-06-07-ops-control-plane-hardening.md`
