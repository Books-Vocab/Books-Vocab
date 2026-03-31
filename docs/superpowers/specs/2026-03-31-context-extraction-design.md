# Translation Context Extraction — Design Spec

## Problem

TXT 檔（如 LINE 聊天記錄匯出）翻譯單詞時 422 失敗。根因鏈：

1. **TXT→EPUB 轉換** 以 `\n\n` 分段，LINE 聊天只有 `\n` → 整文件成一個 `<p>`
2. **JS 分句 regex** `/[.!?]/` 不認中文 `。！？` → 中文內容無法分句
3. 兩者疊加 → `extractContextFromElement` 回傳整個文件內容（數萬字元）
4. Backend `context: Field(max_length=5000)` reject → 422

## Solution — 3 層修復

### Layer 1: TXT 分段（根因）

`splitTXTIntoChapters` 從 `\n\n` 改為 `\n` 分段。每行成為獨立 `<p>`。
- 聊天記錄：每行一段，`findContextContainer` 找到合理的 `<p>`
- 小說：每行一段，比原本更細但排版正常
- 空行（連續 `\n`）跳過，不產生空 `<p>`

### Layer 2: JS 用 `Intl.Segmenter`（核心改善）

用 `Intl.Segmenter`（Safari 14.1+ 原生 API）取代手寫 regex。
- 正確處理 `。！？` 等 CJK 標點
- 自動處理縮寫（`Mr.` `U.S.`）不誤斷
- 回傳「前一句 + 當句 + 後一句」
- `findContextContainer` 加大小防護（textContent > 2000 時往下找更小容器）
- Fallback：`Intl.Segmenter` 不可用時用擴充 regex（加 `。！？\n`）

### Layer 3: Backend 防禦

- `normalize_context` validator：超長時自動截斷而非 reject（已加）
- `context` max_length 降到 1000（prompt 只用 300，5000 毫無意義）
- prompt 的 `context[:300]` 改為 word-centered 截斷

### iOS client 防禦

- `callBackend` 的 context cap 從 4000 降到 600（配合 JS 端 ~500 output）

## Non-goals

- 雙層 context（narrow/broad）— 未來優化
- Range-based DOM 遍歷 — 過度工程
- MD 轉換的分段修復 — 另案
