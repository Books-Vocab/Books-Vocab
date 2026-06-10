<!-- doc-meta
tier: archive
authority: frozen
update_trigger: none
scope:
  - ops/
  - docs/
verified_against: frozen
-->
# Ops Control Plane Hardening Plan

> 歸檔於 2026-06-10：所有編號項目皆已落地（35 ✅）。唯一未勾項「持續把高頻 raw `run` 用法轉成 typed subcommand」為持續性紀律，由 CLAUDE.md 鐵律 9（工具摩擦優先修工具）承接，不留在 plan 內追蹤。

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

8. ✅ `ios_ops.sh logs` 補 Xcode Console 對應的 JSON runtime log 面。
   - 方向:agent 第一輪要能取得 runtime log 摘要與 entries,不用自行解析 compact console 文字。
   - 決策:`logs --json` 走 Apple Unified Logging 官方 CLI `/usr/bin/log show --style ndjson`,輸出 `kg.ios.logs.v1`;保留文字模式,兩者共用 RunningBoard/WebKit assertion 噪音過濾;`--limit` 控制 entries 數。底層 `log show` 失敗必須保留 exit code/stderr,不可被文字過濾 pipeline 吞掉。
   - 驗證:`KG_IOS_OPS_LOG_FIXTURE=1 ./ops/ios_ops.sh logs --json --since 1m --limit 1 | jq ...`、fixture text filtering、bad limit regression、log failure propagation regression、`./ops/test_ops.sh ios-ops`。

9. ✅ `ios_ops.sh snapshot/dashboard` 可選內嵌 runtime logs。
   - 方向:agent 第一輪需要完整觀測時,一條 read-only command 同時拿到 release dashboard、最近 build/test report 與 Xcode Console 摘要。
   - 決策:`snapshot --json` 預設仍快且不查 unified log,輸出 `logs:null`;加 `--include-logs --log-since <duration> --log-limit <n>` 時內嵌 `kg.ios.logs.v1`。文字 dashboard 同樣可用 `--include-logs` 追加 logs phase。
   - 驗證:`KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_LOG_FIXTURE=1 ./ops/ios_ops.sh snapshot --json --include-logs --log-since 1m --log-limit 1 | jq ...`、default `logs:null` fixture、bad `--log-limit` regression、`./ops/test_ops.sh ios-ops`。

10. ✅ `ios_ops.sh commands/capabilities` 補自描述 command catalog。
   - 方向:agent 不應靠 help 文字或 docs 記憶推斷 side-effect、delegate 與 JSON schema。
   - 決策:`commands --json` 輸出 `kg.ios.commands.v1`,列每個 subcommand 的 key、aliases、sideEffect、delegate、purpose、jsonSchemas;文字模式保留 `[ios][command]` 行供人掃描。
   - 驗證:`./ops/ios_ops.sh commands --json | jq ...`、catalog text fixture、`./ops/test_ops.sh ios-ops`。

11. ✅ `ios_ops.sh gate/verdict` 補 release hard-stop verdict。
   - 方向:agent/CI 不只要知道下一步,還要能在第一輪用穩定 exit code 判斷發版是否可繼續。
   - 決策:`gate release --json` 輸出 `kg.ios.gate.v1`,重用 `doctor --json` + `workflow release --json`;exit code 固定 `0=pass`、`1=warn`、`2=block`。`todo`/`manual` 進 `todos[]`/`manual[]`,但不讓 gate 永遠失敗;只有 readiness/workflow `status=block` 會變成 hard block。
   - 驗證:fixture pass / unknown TestFlight build warn / duplicate TestFlight build block 三態,`./ops/test_ops.sh ios-ops`。

12. ✅ `ios_ops.sh snapshot/dashboard` 內嵌 release gate。
   - 方向:agent 第一輪狀態拉取應同時知道 release verdict,不用 snapshot 後再多叫一次 gate。
   - 決策:snapshot 重用同一份 doctor/workflow JSON 計算 `gate`,避免二次查 ASC/TestFlight;`snapshot --json` 自己仍是觀測入口,不因 gate warn/block 回傳非零。
   - 驗證:`KG_IOS_OPS_FIXTURE=1 ./ops/ios_ops.sh snapshot --json | jq '.gate.schema=="kg.ios.gate.v1"'`、`./ops/test_ops.sh ios-ops`。

13. ✅ `ios_ops.sh xcode/environment` 補 Xcode GUI destination/device 視角。
   - 方向:agent 要能像 Xcode scheme/destination selector 一樣看到 project schemes、targets、available destinations、simulator devices 與 booted state,不用手動跑多條 Apple CLI。
   - 決策:`xcode --json` 輸出 `kg.ios.xcode.v1`,組合 `xcodebuild -version`、`xcode-select -p`、`xcodebuild -list -json`、`xcodebuild -showdestinations`、`xcrun simctl list devices --json`;destinations section-aware 分成 `available[]` / `ineligible[]`,各來源都有 status,失敗仍回可解析 JSON + `errors[]`;`environment` 是文字 alias。
   - 驗證:fixture JSON/text regression、ineligible destination regression、source failure regression、真實 `xcode --json` smoke、`./ops/test_ops.sh ios-ops`。

14. ✅ `ios_ops.sh snapshot/dashboard` 預設內嵌 Xcode inventory。
   - 方向:agent 第一輪 `snapshot --json` 就要拿到 project/readiness/workflow/gate/xcode/runs,不用 snapshot 後再跑 `xcode --json`。
   - 決策:snapshot 預設內嵌 `kg.ios.xcode.v1`;需要快速 dashboard 時可用 `--skip-xcode`,此時 `xcode:null`。runtime logs 仍維持 `--include-logs` 才查。
   - 驗證:fixture default snapshot 驗 `.xcode.schema=="kg.ios.xcode.v1"`,skip fixture 驗 `.xcode==null`,`./ops/test_ops.sh ios-ops`。

15. ✅ `ios_ops.sh simulator/sim` 補 Simulator GUI 截圖協作面。
   - 方向:agent 要能用統一入口完成 booted simulator 狀態檢查、app data container 查詢與 screenshot artifact capture,不用手動組多條 `xcrun simctl`。
   - 決策:`simulator status --json` / `simulator screenshot --out <png> --json` 輸出 `kg.ios.simulator.v1`;status read-only,screenshot 只產生本機 PNG artifact,不 boot/install、不改 ASC。新增實作放 `ops/lib/ios_ops_simulator.sh`,主 `ios_ops.sh` 保持 façade/dispatcher,後續肥厚區塊沿同模式拆。
   - 驗證:fixture JSON/text regression、含空白路徑 screenshot artifact regression、no booted simulator error JSON + exit 1 regression、`./ops/test_ops.sh ios-ops`。

16. ✅ `ios_ops.sh xcode/environment` 實作拆成 sourceable lib。
   - 方向:`ios_ops.sh` 應維持統一入口 / catalog / dispatcher / shared providers,不要長期承擔每個 GUI parity surface 的完整 implementation。
   - 決策:把 `kg.ios.xcode.v1` 的 `cmd_xcode_json` / `cmd_xcode` 搬到 `ops/lib/ios_ops_xcode.sh`;主檔只 source lib。測試固定 lib 存在、語法、source 邊界,避免後續又把大塊實作塞回 façade。
   - 驗證:`KG_IOS_OPS_FIXTURE=1 ./ops/ios_ops.sh xcode --json | jq ...`、`./ops/test_ops.sh ios-ops`。

17. ✅ `ios_ops.sh logs` 實作拆成 sourceable lib。
   - 方向:`logs` 對應 Xcode Console 視角,但 implementation 不應塞在統一入口主檔;GUI parity surface 要能獨立維護與測試。
   - 決策:把 `kg.ios.logs.v1` 的 text/json、noise filtering、`log show` failure propagation 與 fixture 搬到 `ops/lib/ios_ops_logs.sh`;主檔只保留 shared constants + source。測試固定 lib 存在、語法、source 邊界。
   - 驗證:`KG_IOS_OPS_LOG_FIXTURE=1 ./ops/ios_ops.sh logs --json --since 1m --limit 1 | jq ...`、`./ops/test_ops.sh ios-ops`、review PASS。

18. ✅ `ios_ops.sh runs/reports` 實作拆成 sourceable lib。
   - 方向:`runs` 對應 Xcode Report Navigator 視角,應與 logs/xcode/simulator 一樣成為可獨立維護的觀測 surface。
   - 決策:把 `kg.ios.runs.v1` 的 verdict JSON normalization、legacy fallback、malformed JSON handling 與 text report 搬到 `ops/lib/ios_ops_runs.sh`;主檔保留 verdict path/shared helper 與 snapshot 組合。
   - 驗證:含空白 artifact path fixture、missing/malformed verdict fixture、text fallback fixture、`./ops/test_ops.sh ios-ops`、review PASS。

19. ✅ `ios_ops.sh snapshot/dashboard` 實作拆成 sourceable lib。
   - 方向:`snapshot` 是 agent 第一輪 dashboard 入口,但仍應像其他 GUI parity surface 一樣獨立維護,主檔只保留 catalog/dispatch/shared helper。
   - 決策:把 `kg.ios.snapshot.v1` 的 doctor/workflow/gate/xcode/runs/logs 組合與 text dashboard orchestration 搬到 `ops/lib/ios_ops_snapshot.sh`;source 順序固定在 logs/xcode/runs lib 之後。
   - 驗證:default snapshot、`--skip-xcode`、`--include-logs`、bad `--log-limit`、logs failure propagation fixtures、`./ops/test_ops.sh ios-ops`、review PASS。

20. ✅ `ios_ops.sh doctor/workflow/gate/sentry` release surface 實作拆成 sourceable lib。
   - 方向:`doctor`/`workflow`/`gate` 是發版控制面的核心,但 implementation 不應留在統一入口主檔;主檔應只負責 catalog、shared providers、fixture adapters 與 dispatch。
   - 決策:把 readiness emitters、`doctor_readiness`、Sentry 摘要、release workflow JSON/text、release gate verdict 計算搬到 `ops/lib/ios_ops_release.sh`;`ios_ops.sh` source 順序固定為 logs → release → xcode → simulator → runs → snapshot,確保 snapshot 能重用 doctor/workflow/gate。
   - 驗證:先加 release lib 邊界 regression 並確認紅燈,搬移後 `./ops/test_ops.sh ios-ops` 122 shell checks + 6 pytest 通過,完整 `./ops/test_ops.sh` 13 groups / 0 failed,review PASS。`ios_ops.sh` 從 967 行降到 532 行。

21. ✅ `ios_ops.sh commands/capabilities` 實作拆成 sourceable lib。
   - 方向:`commands` 是 agent 自描述 catalog,但 catalog implementation 不應留在統一入口主檔;主檔應只保留 usage、shared providers、fixture adapters、source 與 dispatch。
   - 決策:把 `kg.ios.commands.v1` JSON catalog 與 text formatter 搬到 `ops/lib/ios_ops_commands.sh`;測試固定 lib 存在、語法、source 邊界,並加負向斷言禁止 `ios_ops.sh` 重新定義 `cmd_commands` / `cmd_commands_json`。
   - 驗證:先加 commands lib 邊界 regression 並確認紅燈,搬移後 `./ops/test_ops.sh ios-ops` 127 shell checks + 6 pytest 通過,完整 `./ops/test_ops.sh` 13 groups / 0 failed,review PASS。`ios_ops.sh` 從 532 行降到 358 行。

22. ✅ `ios_ops.sh` shared providers / fixture adapters / core helpers 拆成 sourceable lib。
   - 方向:統一入口主檔不應承擔 Xcode/ASC/simctl provider、fixture override、capture adapter、verdict helper 等 shared core implementation;這些應成為所有 iOS ops surface 共用的底座。
   - 決策:把 `ROOT`/`XCODEPROJ`/`SCHEME`/`BUNDLE_ID`/logging constants、project/Organizer/TestFlight/ASC/Xcode/simctl readers、fixture providers、`capture_source_*`、verdict path helpers 與 artifact existence helper 搬到 `ops/lib/ios_ops_core.sh`;`ios_ops.sh` 只保留 usage、source、`cmd_status` shim 與 dispatch。測試新增 source order monotonic check(core → commands → logs → release → xcode → simulator → runs → snapshot)與完整 core function 負向斷言。
   - 驗證:先加 core lib 邊界 regression 並確認紅燈,搬移後 `./ops/test_ops.sh ios-ops` 172 shell checks + 6 pytest 通過,完整 `./ops/test_ops.sh` 13 groups / 0 failed,review PASS。`ios_ops.sh` 從 358 行降到 94 行。

23. ✅ `ios_ops.sh simulator status` 補 app process 狀態。
   - 方向:對齊 Xcode toolbar 的 Running app 視角,agent 第一輪 simulator status 不只要知道 booted device / app data container,也要知道 BooksAndVocab 是否正在 simulator 內執行。
   - 決策:`kg.ios.simulator.v1` 新增 `app.process{name,pid,status,exitCode,error}` 與 `sources.app_process`;底層用 read-only `xcrun simctl spawn <device> pgrep -x BooksAndVocab`。`process.status=running|stopped|skipped|unknown`;app stopped(`pgrep` exit 1)是觀測狀態,不讓 `simulator status` 失敗且不進 `errors[]`;意外 provider failure 才列 `errors[]`。
   - 驗證:running fixture、stopped fixture、text output、core provider boundary regression、`./ops/test_ops.sh ios-ops` 175 shell checks + 6 pytest 通過,完整 `./ops/test_ops.sh` 13 groups / 0 failed,review PASS。同步 `docs/sop/ios.md`、`docs/reference/tech_index.md`、`docs/reference/product_surface.md`。

24. ✅ `ios_ops.sh snapshot/dashboard` 內嵌 simulator 狀態。
   - 方向:agent 第一輪 dashboard 要同時知道 Xcode destination inventory 與 Xcode toolbar 的 Running app 狀態,不用 snapshot 後再跑 `simulator status --json`。
   - 決策:snapshot 預設內嵌 `kg.ios.simulator.v1`;需要快速 dashboard 時可用 `--skip-simulator`,此時 `simulator:null`。沒有 booted simulator 是觀測缺口,會保留 `.simulator.status="error"` 與 `errors[]` 並讓 snapshot exit 0;runtime logs provider failure 仍傳遞非零 exit。
   - 驗證:fixture default snapshot 驗 `.simulator.schema=="kg.ios.simulator.v1"` 與 app process running,skip fixture 驗 `.simulator==null`,no-booted fixture 驗 `.simulator.status=="error"` 且 snapshot 不失敗,commands catalog schema regression,`./ops/test_ops.sh ios-ops`。

25. ✅ `ios_ops.sh runs/snapshot` 內嵌最新 build/test diagnostics。
   - 方向:編譯警告、錯誤與測試失敗是 Xcode Issue Navigator / Report Navigator 的核心資訊,agent 第一輪 dashboard 應直接看到,不用再二次跑 `issues` 或 grep log。
   - 決策:`runs --json` 在 build/test run 物件內新增 `diagnostics`:`kg.ios.diagnostics.v1`,優先用 `.xcresult`,fallback raw log;缺 artifact 時輸出 `source:"missing-artifacts"` 的穩定空摘要。`snapshot --json` 因內嵌同一份 `runs` 自動帶出 `.runs.build.diagnostics` / `.runs.test.diagnostics`。
   - 驗證:先加 fixture regression 使 `runs --json` / `snapshot --json` 要求 StoreKit warning diagnostics 並確認紅燈;實作後 `./ops/test_ops.sh ios-ops` 通過。

26. ✅ `ios_ops.sh snapshot/dashboard` 補頂層 summary / nextActions。
   - 方向:Xcode 第一屏不只給原始 panes,也讓人直接看到紅黃燈與下一個可處理問題;agent 第一輪不應自己掃深層 JSON 才知道優先級。
   - 決策:`snapshot --json` 新增 `summary.verdict=pass|warn|block`、`summary.counts` 與 `summary.nextActions[]`。來源包含 release gate blocks/warnings/todos、build/test diagnostics、Xcode source errors、Simulator observation errors 與 runtime log count。gate todo 不讓 verdict 變 warn;build/test errors 或 gate blocks 才是 block,warning/observability gap 是 warn。
   - 驗證:先加 fixture regression 要求 build StoreKit warning 讓 `.summary.verdict=="warn"` 且 `nextActions[]` 指向 `runs.build.diagnostics`;no-booted simulator 進 `nextActions[]`;include-logs 更新 runtime count。實作後 `./ops/test_ops.sh ios-ops` 通過。

27. ✅ `ios_ops.sh snapshot/dashboard` 文字模式改為 summary-first。
   - 方向:人類 terminal 第一屏也要和 JSON dashboard 一樣先看到 verdict / next actions,而不是舊式 phase dump。
   - 決策:非 JSON `snapshot` 改為先產生同一份 `kg.ios.snapshot.v1` payload,再格式化 `[ios][summary]`、`[ios][next]` 與高層 project/gate/runs/xcode/simulator/logs 行。移除 text mode 的 `phase=doctor` / `phase=workflow` dump,避免 JSON/text 判讀規則漂移。
   - 驗證:fixture regression 要求 `snapshot` 第一行為 `[ios][summary] ... verdict=warn ... buildWarnings=1`,且列出 `source=runs.build.diagnostics` 的 `[ios][next]`,並禁止 `phase=doctor`;`./ops/test_ops.sh ios-ops` 通過。

28. ✅ `ios_ops.sh simulator/sim` 補 Xcode Run/Stop toolbar 的 lifecycle 窄面。
   - 方向:GUI parity 不能只看 app process / 截圖;agent 也要能透過統一入口啟動或停止已安裝的 BooksAndVocab,並立即取得 process re-check。
   - 決策:`simulator launch --json` / `simulator terminate --json` 共用 `kg.ios.simulator.v1`,底層只包官方 `xcrun simctl launch|terminate`。payload 新增 `app.lifecycle{status,exitCode,output,error}` 並在命令後重新讀 `app.process`;這是 local simulator side effect,不 build、不 install、不 boot、不改 ASC。`commands --json` 的 `sideEffect` 明確標成 `local-simulator-lifecycle launch/terminate`。
   - 驗證:fixture regression 要求 stopped app 可 `launch` 後 process=running/pid=74736,`terminate` 後 process=stopped,文字模式列 action/status/process;core provider boundary 固定 `read_app_launch_output` / `read_app_terminate_output`;`./ops/test_ops.sh ios-ops` 通過。

## 驗證矩陣

- `./ops/test_ops.sh docs-lint`
- `./ops/test_ops.sh python-entrypoints`
- `./ops/test_ops.sh ios-ops`
- `KG_IOS_OPS_LOG_FIXTURE=1 ./ops/ios_ops.sh logs --json --since 1m --limit 1 | jq ...`
- `KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_LOG_FIXTURE=1 ./ops/ios_ops.sh snapshot --json --include-logs --log-since 1m --log-limit 1 | jq ...`
- `./ops/ios_ops.sh commands --json | jq ...`
- `KG_IOS_OPS_FIXTURE=1 ./ops/ios_ops.sh gate release --json | jq ...`
- `KG_IOS_OPS_FIXTURE=1 ./ops/ios_ops.sh snapshot --json | jq '.gate.schema=="kg.ios.gate.v1"'`
- `KG_IOS_OPS_FIXTURE=1 ./ops/ios_ops.sh xcode --json | jq '.schema=="kg.ios.xcode.v1"'`
- `KG_IOS_OPS_FIXTURE=1 ./ops/ios_ops.sh snapshot --json | jq '.xcode.schema=="kg.ios.xcode.v1"'`
- `KG_IOS_OPS_FIXTURE=1 ./ops/ios_ops.sh snapshot --json | jq '.summary.verdict and (.summary.nextActions|type=="array")'`
- `KG_IOS_OPS_FIXTURE=1 ./ops/ios_ops.sh simulator status --json | jq '.schema=="kg.ios.simulator.v1"'`
- `KG_IOS_OPS_FIXTURE=1 ./ops/ios_ops.sh simulator launch --json | jq '.action=="launch" and .app.process.status=="running"'`
- `KG_IOS_OPS_FIXTURE=1 ./ops/ios_ops.sh simulator terminate --json | jq '.action=="terminate" and .app.process.status=="stopped"'`
- `KG_IOS_OPS_FIXTURE=1 ./ops/ios_ops.sh simulator screenshot --out /tmp/kg-sim.png --json | jq '.artifact.exists==true'`
- `TMPDIR=<fixture> ./ops/ios_ops.sh runs --json | jq '.build.diagnostics.schema=="kg.ios.diagnostics.v1"'`
- `./ops/test_ops.sh ios-release` 或等效 release surface group
- `./ops/test_ops.sh asc` 或等效 ASC group
- `./ops/docs_lint.sh --files docs/plans/2026-06-07-ops-control-plane-hardening.md`
