<!-- doc-meta
tier: archive
authority: derived
update_trigger: manual
scope:
  - backend/
verified_against: frozen
-->

# Backend 技術債與品質審查

審查日期: 2026-06-11 ｜ 基準 commit: `624f0c32` ｜ 方法: 4 維平行 Explore agent + 真實 coverage/ruff 量測

> **archive tier**：凍結於上述基準的一次性 audit，不更新、不引用。需要當前狀態請重跑 coverage/ruff 並讀對應 sop/reference。

## 規模與總評

| 指標 | 值 |
|------|----|
| 源碼 | 176 檔 / 26,467 行 |
| 測試 | 216 檔 / 47,112 行 |
| Coverage（全量） | **87%**（11,510 stmt / 1,532 miss） |
| 測試結果 | 2,658 passed / **1 failed** |
| ruff | **438 errors**（無 CI gate） |

**總評 B+ / 7.5**：架構地基穩、安全無可利用洞、覆蓋 87% 健康。債集中於三處 — lint 無 gate、event-loop 阻塞、一個測試順序污染 bug。

---

## P0 — 立即處理（高影響 / 低成本）

### 1. 測試套件順序污染 bug（恢復 CI 可信度）
- `tests/test_orphan_scan.py::test_fix_aborts_when_graph_file_mutated_mid_run`
- **單獨跑 passed，全量套件中穩定 failed** → 非 timing flaky，是模組級全局狀態污染（前置測試未清乾淨）。
- 影響：全量綠靠 `-x`/單跑掩蓋，CI 上會紅。根因候選：`orphan_scan` graph-file 模組狀態 / `tests/conftest.py:404` `_USER_LOCKS.clear()` 一類全局重置。

### 2. 無 ruff CI gate，438 errors 裸奔
- 拆解：378 `F405`（star-import 衍生）、51 `F401`（unused）、7 `I001`（import order）。
- 根因：9 處 `import *`，主源為 5 個 `ops_edit_*_commands.py` 的 `from .ops_edit_support import *`：

  | 檔案 | F405 |
  |------|------|
  | `src/kg/ops_edit_seed_commands.py` | 103 |
  | `src/kg/ops_edit_card_commands.py` | 101 |
  | `src/kg/ops_edit_user_commands.py` | 83 |
  | `src/kg/ops_edit_link_commands.py` | 55 |
  | `src/kg/ops_edit_notebook_commands.py` | 36 |

- 修法：① `ops_edit_support.py` 加 `__all__` 收編 51 個有意 re-export（一舉清掉大半 F401 噪音）；② 五個 cmd_* 改顯式 import（`argparse/json/Path/Any` 直接 import、helper 具名 import）；③ `ruff --fix` 自動清 58 個；④ 加 `ops/` lint gate 釘住防復發。
- ⚠️ `src/kg/api.py ← api_compat`、`src/kg/admin_handlers.py:17 ← admin` 的 `import *` 是**刻意 compat shim**，標 `# noqa: F403` 別誤清。

### 3. `admin_wiring.py` 25 個巢狀 handler 全缺 return type
- type 覆蓋僅 17%；類型檢查盲區。return type 可半自動補。

---

## P1 — 真實風險，排程處理

### 4. async route 阻塞 event loop（架構 High）
- `src/kg/admin_wiring.py:341-357` `admin_log_retention_run()` 同步跑 5 個 SQLite DELETE，**未** `run_in_threadpool` — 隔壁 `admin_orphans_scan()`（`:388`）已正確包裝，照抄即可。
- `src/kg/routers/system.py:59` `/api/system/info` 同步呼叫 `observability_alerts.run_all_checks()`（掃多個 log 檔），健康檢查 endpoint 反覆阻塞。

### 5. 外部呼叫無重試 / 無熔斷（可靠性 High）
- `src/kg/routers/web_auth.py:154-166` Google token exchange 單次 `timeout=10` 失敗即 502 → 網路抖動 = 登入失敗。加 2-3 次指數退避。
- LLM 呼叫全鏈無斷路器，下游慢時無保護。

### 6. 單元測試空洞 — 核心模組覆蓋薄
真實低覆蓋熱點（已濾掉 CLI/init 樣板）：

| 模組 | cov | 風險 |
|------|-----|------|
| `src/kg/vocab_review.py` | **16%** | 複習核心邏輯幾乎沒測 |
| `src/kg/routers/podcast_media.py` | 18% | S3 讀取 + 502 錯誤路徑 |
| `src/kg/routers/podcast_playback.py` | 25% | |
| `src/kg/secret_store.py` | **29%** | 加密金鑰處理（敏感） |
| `src/kg/podcast_progress.py` | 32% | |
| `src/kg/routers/web_auth.py` | 35% | OAuth 流程（同 #5） |
| `src/kg/quota_service.py` | 71% | **邊界缺**：並發預留雙花、跨午夜 rolling window |
| `src/kg/vocab_crud.py` | 60% | data 層核心 |

低覆蓋但可接受（樣板）：`ops_cli_parser`(9%)、`ops_edit_parser`(5%)、`ops_edit_seed_commands`(3%)、`sentry_init`(28%)。

---

## P2 — 結構債

### 7. `quota_service` 正確性綁死 `--workers 1`
- 已驗 `Dockerfile:48` `--workers 1` + 註解鎖定，**非 active 風險**。但隱性單點：改多 worker / 多副本 → Free 用戶配額 N 倍超支，且無測試擋。`src/kg/quota_service.py:117-200` 的並發預留 + rolling window 邊界完全沒測。建議補一條「多 worker 會雙花」回歸測試標記意圖。

### 8. ops_edit_* 系列肥大（3.2k 行）+ `admin_wiring` 巨工廠
- `ops_edit_support.py`(586) 內聚度尚可、cmd_* 樣板提煉 ROI 低（抽象反降可讀性）。**唯一值得做**：`admin_wiring.py:96-450` 改 spec-table 驅動（25 個無共用邏輯的閉包）。其餘列為風格潔癖，勿過度重構。

### 9. SQLite 全局單例連線
- 全程 `threading.Lock` 序列化（`judge_log.py:27-55`、`service_factories.py:22-26`），慢查詢卡住同 worker 其他請求。單 worker 下可接受，是 #7 單點的另一面。

### 其他 Low
- `src/kg/log_retention.py:86-91` DELETE + COUNT 無交易保護，並發寫入時 count 不準。
- `src/kg/graph/filelock.py:39-40` Windows 無 fcntl 時退化無操作，多進程開發環境易漏 race。
- `src/kg/enrich.py:190-193` 每 request 建 `ThreadPoolExecutor`，多 worker 下過度建執行緒。
- 配置分散：21 處散落 `os.getenv`，secret 相關（`secret_store.py`、`app_store.py:50-74`、`sentry_init.py`、`llm/providers.py`）無統一驗證/載入；建議集中 `secrets.py` + 啟動期驗證必填 env。

---

## 測試品質債（非覆蓋率）
- **斷言過弱**：~30-40% 的 `status_code == 200` 後不驗 body。建議 conftest 加 `assert_api_success(resp, schema)` helper。
- **flaky 風險（timing）**：`tests/test_pipeline_log.py:61/94/96`、`tests/test_google_auth.py:241/260/263` 用 `time.sleep(0.01~0.1)` 保證時序/模擬 I/O → 改 `monkeypatch` 掉 sleep。
- **硬編 `/tmp`**：`tests/test_admin_wiring_contracts.py:19/50`、`test_app_router_composition.py` 用 `Path("/tmp/...")` 而非 `tmp_path`，CI 禁寫 /tmp 會假失敗。
- **過度 mock**：`tests/test_podcast_media.py` 全 `MagicMock`，測 implementation 而非契約。
- **全局狀態污染**：`tests/conftest.py:404-406` `_USER_LOCKS.clear()` + `_USER_LOCKS_MUTEX = None`，`pytest -n` 並行會競爭（目前未並行，無註記）。同 #1。

---

## ✅ 做得好的（勿動）
- **LLM provider 抽象**（`llm/providers.py`）：env 驅動、零適配器、可 A/B 動態換 — 業界級。
- **append-only ledger**：`graph_event_log.py` / `review_events.py` 單調 cursor + snapshot checkpoint + 區分 synthetic/real。
- **安全面**：JWT 算法白名單（`user_context.py:42`）、`secrets.compare_digest` 防時序（`web_auth.py:69`）、tarfile `filter="data"` 防遍歷（`ops_edit_support.py:318`）、user_id 白名單 `^[a-zA-Z0-9_.-]+$`、Sentry scrub headers/query + `send_default_pii=False`。**無 SQL 注入、無路徑遍歷漏洞**。
- **測試隔離設計**：conftest 5 個 autouse fixture + `tmp_path` 真實 SQLite（非 mock）。

---

## 建議執行順序（ROI）
1. 修測試污染（#1）→ 恢復全量綠的可信度
2. ruff `__all__` + 顯式 import + `--fix` + lint gate（#2）→ 438 降個位數、防復發
3. 兩處 `run_in_threadpool`（#4）→ 10 分鐘照抄隔壁
4. `web_auth` retry（#5）→ 解登入抖動掉線
5. 中期：`admin_wiring` spec-table 重構 + return type（#3/#8）、`vocab_review`/`podcast_media`/`quota_service` 邊界補測（#6）

建議 1-4 打包單一低風險 PR，當下可驗證。
