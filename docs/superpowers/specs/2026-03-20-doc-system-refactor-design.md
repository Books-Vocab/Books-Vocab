# Doc System Refactor — Design Spec

Date: 2026-03-20
Status: approved

## 目標

重構文件系統，使其以 Claude agent 為第一讀者，解決三個問題：
1. 內容過時（stale content）— 文件描述的架構/檔案與現在的 code 不符
2. 組織混亂 — 行銷/法務/開發文件混在同一層，分類不清楚
3. 計劃垃圾堆積 — 已執行的 plans 沒人清理，形成 agent 雜訊

---

## Section 1：目錄結構

### 新結構

```
docs/
├── dev/                     # 開發主入口（6 個核心文件）
│   ├── architecture.md
│   ├── backend-dev.md
│   ├── deploy.md
│   ├── debug.md
│   ├── ios-dev.md
│   └── ui-design.md
├── references/              # 深度參考（保留現有 14 個）
├── superpowers/
│   ├── specs/               # 設計文件
│   ├── plans/               # 僅放未執行的計劃
│   └── archive/             # 已執行的計劃（不被 agent load）
└── assets/                  # 行銷/法務/截圖
    ├── screenshots/
    ├── PRIVACY_POLICY.md
    ├── eula_plaintext.txt
    ├── promo-video-prompts.md
    └── screenshot-framing.md
```

### CLAUDE.md 更新

Reference Docs 表格只指向 `docs/dev/` + `docs/references/`，移除 `assets/` 的任何引用。

---

## Section 2：Frontmatter 規格

每份 `docs/dev/` 和 `docs/references/` 的 `.md` 頂部加：

```html
<!-- doc-meta
tier: structural | operational | snapshot | reference
scope:
  - ios/BooksBrowser/Services
  - backend/src/kg
verified_against: a1b2c3d
-->
```

### 欄位定義

| 欄位 | 說明 |
|---|---|
| `tier` | 文件類型，決定更新頻率與更新方式 |
| `scope` | 對應的程式碼目錄，agent 判斷相關性用 |
| `verified_against` | 驗證時的 git short SHA（7碼） |

### Tier 定義

| Tier | 文件範例 | 更新時機 |
|---|---|---|
| `structural` | architecture.md, ui-design.md | 架構決策或設計系統根本改變時 |
| `operational` | deploy.md, debug.md | ops 流程或指令改變時 |
| `snapshot` | ios_frontend_baseline.md | 重大重構後跑再生腳本 |
| `reference` | ui_review_checklist.md, sync_lifecycle.md, ui_component_pattern_inventory.md | pattern 新增或廢棄時 |

### Agent 行為規則（寫入 CLAUDE.md）

- 修改任何有 `doc-meta` 的文件後，自動更新 `verified_against` 為當前 commit SHA
- 讀到 `tier: snapshot` 時，優先跑再生腳本而非手動編輯

---

## Section 3：Snapshot 再生腳本

### `ops/gen_ios_baseline.sh`

再生 `docs/references/ios_frontend_baseline.md`，輸出：
- Swift 檔案行數 Top 10（`find` + `wc -l`）
- 總行數 / 總 Swift 檔案數
- `#Preview` 覆蓋率（`grep` 計數）
- `@MainActor` / `async` 使用統計

實作：純 shell，`find` + `wc -l` + `grep`，無外部依賴，執行 < 1 秒。

觸發時機（寫入 CLAUDE.md）：任何涉及 iOS 大規模重構的 PR 合併後執行。

### `ui_component_pattern_inventory.md` 不適合腳本再生

內容為語意描述，無法從 code 抽取。改為 `tier: reference`，靠 frontmatter 管理。

---

## Section 4：Plans 清掃規則

### 歸檔判斷依據

計劃對應的 feature 若已在 `git log` 中出現（PR 已合併），移至 `docs/superpowers/archive/`。

### 已確認可歸檔（對應已合併 PR）

- `2026-03-19-swiftdata-perf.md` → PR #199
- `2026-03-19-service-layer-refactor.md` → PR #198

### 需逐一確認

以下計劃需比對 git log 確認是否已執行：
- 2026-03-18: backend-tech-debt, critical-bugfix-sweep, network-layer-unification, overview-tab-promotion
- 2026-03-19: animation-convenience, banner-unify, concurrency-modernize, reader-settings-unify, settings-row-inline, sheet-modifier, vocab-scene-shell

---

## 實作順序

1. 建立 `docs/dev/`、`docs/assets/`、`docs/superpowers/archive/` 目錄，移動檔案
2. 為所有 `docs/dev/` + `docs/references/` 文件加 frontmatter
3. 確認並歸檔已執行的 plans
4. 撰寫 `ops/gen_ios_baseline.sh` 並執行，更新快照
5. 更新 CLAUDE.md（Reference Docs 表 + agent 行為規則）
