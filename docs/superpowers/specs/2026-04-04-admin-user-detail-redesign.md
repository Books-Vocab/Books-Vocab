---
title: Admin User Detail Page Redesign
date: 2026-04-04
status: draft
scope: backend/src/kg/admin_user_detail.html
backend_changes: none
estimated_lines: 1300-1400
---

# Admin User Detail Page Redesign

## 目標

重構 `admin_user_detail.html`（現 1237 行），將五張卡片整併為三張表格，改為雙欄佈局，並以純 CSS 瀑布圖取代 Chart.js 全域統計圖表。

## 佈局

### 雙欄結構

```
Container: display: flex; gap: 24px; max-width: 1320px
├── Left column (340px, position: sticky, top: 52px)
│   ├── Table 1: 帳戶基本資訊
│   ├── Table 2: 訂閱狀態
│   └── Table 3: 額度使用狀態
└── Right column (flex: 1, scrollable)
    ├── Pipeline Runs (expandable list)
    ├── Graph Density Chart
    └── Graph Playback
```

- 左欄 `position: sticky; top: 52px`（52px = nav 高度），內容超過 viewport 時獨立捲動
- 右欄自然文件流捲動

## 卡片整併：5 → 3 表格

### Table 1: 帳戶基本資訊（靜態）

| 欄位 | 來源 |
|------|------|
| User ID | 現有 |
| Email | 現有 |
| Provider | 現有 |
| 最後登入 | 現有 |
| 單字數 | 現有 |
| Mochi 整合 | 現有 |

### Table 2: 訂閱狀態（合併訂閱狀態 + Admin Grant）

上半部 — 訂閱：

| 欄位 |
|------|
| Pro 啟用 |
| 狀態 |
| 來源 |
| 方案 |
| 價格 |
| 到期日 |
| 試用 |
| 自動續訂 |

Divider + 子標題 "Admin Grant"

下半部 — Grant：

| 欄位 |
|------|
| 啟用 |
| 授權者 |
| 原因 |
| 授權時間 |
| 到期日 |

兩區段永遠可見，不做折疊。Admin 需要一眼看到完整訂閱全貌。

### Table 3: 額度使用狀態（合併每日翻譯額度 + Token 消耗明細）

結構：

1. **頂部**：used / limit + progress bar
2. **中段**：每種 type 一列，格式 `次數 = $費用 | input↑ output↓`
3. **底部** divider：預估總費用

## Pipeline Runs 改版

### 移除

- 全域摘要統計（6 個數字）
- 全域堆疊長條圖（Chart.js）

### 替代方案：可展開列表 + per-run CSS 瀑布時間軸

列表保持現有 run list 樣式。點擊展開後顯示純 CSS 瀑布圖：

```
時間軸標記: 0s          25%         50%         75%        {total}s
            |-----------|-----------|-----------|-----------|
enrich      ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░  2.1s  42
embed       ░░░░░░░░████████████░░░░░░░░░░░░░░░░  3.4s  42
difficulty  ░░░░░░░░░░░░░░░░░░░██████░░░░░░░░░░░  1.8s  42
mochi       ░░░░░░░░░░░░░░░░░░░░░░░░░████████████ 4.2s  38
```

#### 規則

- 每個 step = 一列 + 一條水平 bar
- Bar 起始位置 = `(step.started_at - run.started_at) / total_duration * 100%`
- Bar 寬度 = `step.duration_s / total_duration * 100%`
- 顏色：
  - ok → `var(--ink)`
  - failed → `var(--dev)` (red)
  - skipped → `var(--sub)` (gray)
- 右側標籤：duration, items count
- Failed step 在 bar 下方顯示紅色錯誤訊息
- 頂部時間軸標記：0s, 25%, 50%, 75%, 100%（對應 run 總時長）

#### 實作

純 CSS，不依賴 Chart.js。用 `style` 屬性動態設定 `margin-left` 與 `width` 百分比。

## 檔案策略

維持單一 HTML 檔案，不拆分、不引入 bundler 或 module system。重構後預估 1300-1400 行。

## 後端

**無需任何變更。** 所有資料已由現有 endpoint 提供，僅前端 HTML/CSS/JS 修改。
