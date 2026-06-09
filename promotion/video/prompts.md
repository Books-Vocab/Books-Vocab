<!-- doc-meta
tier: assets
authority: marketing
update_trigger: app-store-asset-refresh
scope:
  - marketing/
-->
# BooksAndVocab 宣傳影片製作指南

純 app 實錄 + 後製。無人物，畫面即主角。
Apple 產品影片風格：乾淨、精準、節奏感。

---

## 敘事弧線

```
遇見 → 收藏 → 複習 → 理解 → 精通
```

4 個鏡頭，每個自成一體，串起來是完整旅程。

---

## Shot 1 — 閱讀中查詞（~7s）

### 錄製內容

1. Reader 頁面，英文小說段落靜止 2s（讓觀眾讀到文字）
2. 手指點擊 "heist" → 金色底線出現
3. 翻譯卡從底部滑出：「搶案」+ 語境解釋
4. 停留 1s 讓觀眾看完內容

### 後製

- **開場**：畫面從全黑 scale up 到 iPhone mockup frame，帶淺景深陰影
- **點擊瞬間**：加一圈極淡的 ripple 光暈（同 app 色調，奶白偏暖）
- **翻譯卡滑出時**：輕微 parallax — 卡片往上滑的同時背景微微下沈 1-2px
- **音效**：柔和的 tap 聲 + 卡片滑出的 woosh

---

## Shot 2 — 複習翻牌（~7s）

### 錄製內容

1. 複習卡 "tome or tale" /「典籍或故事」停留 1.5s
2. 向右滑「記得」→ 卡片飛出 → 下張飛入
3. 向左滑「忘記」→ 卡片飛出 → 下張飛入
4. 向右滑「記得」→ 卡片飛出
5. 三張節奏：慢、快、快（加速感）

### 後製

- **iPhone mockup 微傾斜 3-5°**，帶動態陰影隨卡片滑動方向偏移
- **每張卡片飛出時**：mockup 極輕微隨滑動方向晃動（< 1°）模擬手感
- **「記得」滑動**：軌跡帶一絲綠色光尾
- **「忘記」滑動**：軌跡帶一絲橙色光尾
- **節奏**：第一張 normal speed → 第二三張 1.2x 加速，建立韻律感
- **音效**：每次滑動一聲低頻 swoosh，pitch 逐張微升

---

## Shot 3 — 知識圖譜（Hero Shot）（~9s）

### 錄製內容

1. 從生詞庫切換到「關聯圖」tab
2. 知識圖譜全景 — 節點飄動 2s
3. 雙指慢速縮放展開
4. 點擊 "unkempt" 節點
5. 詞條詳情彈出：引句、釋義「不修邊幅的」、對比 "primped"、易混 "unaided"

### 後製

- **這是全片高潮，給最多時間和最強後製**
- **進場**：前一個 shot 淡出 → 0.5s 純黑 → 圖譜從中心點爆開式 scale in（0→100%），如同星圖展開
- **節點飄動時**：背景加極淡的粒子漂浮（同色系 earth tone，opacity 10-15%）
- **縮放時**：加 smooth ease-in-out 曲線，配合音樂 build-up
- **點擊節點瞬間**：該節點 pulse 一下（scale 100%→115%→100%），連線 highlight
- **詳情彈出**：從節點位置 morph transition 展開成卡片（非普通 sheet 滑出）
- **音效**：ambient pad 持續 + 節點點擊時一聲清脆的 ping + 展開時 shimmer

---

## Shot 4 — 回到閱讀，流暢讀完（~5s）

### 錄製內容

1. Reader 頁面，包含之前查過的 "heist"（帶底線標記）
2. 流暢翻頁 2-3 頁，不停頓
3. 最後停在一個段落

### 後製

- **翻頁速度**：比實際略快（1.3x），傳達「讀得順暢」
- **每次翻頁**：極淡的 page turn blur（motion blur 2-3 frame）
- **"heist" 底線**：第一次出現時微微 glow 0.5s 然後恢復（暗示「這個字你已經會了」）
- **最後 2s**：畫面緩慢 scale down + 加深景深模糊 → iPhone mockup 縮到畫面中央
- **音效**：柔和翻頁聲，逐漸變安靜

---

## 收尾（~2s）

- 上一個 shot 的 mockup 縮至中央 → 淡化為 app icon
- 標語淡入：**「讀到哪，學到哪」**
- 副標（可選）：App Store badge
- 全黑淡出

---

## 全片後製規範

### 色調

| 元素 | 色調 |
|------|------|
| 背景 | 純黑 #000 或深灰 #111（凸顯螢幕亮度） |
| App 螢幕 | 保持原色，微調 contrast +5%、warmth +3% 統一感 |
| 光效 | earth tone only：#C4956A / #8B9467 / #D4A843 / #9B7B8E |
| 整體 grade | 暗部偏暖、亮部乾淨，類似 Apple 產品影片 |

### iPhone Mockup

- 使用純黑 iPhone frame（不搶焦）
- 帶真實感陰影（soft shadow, blur 30px, opacity 40%）
- 每個 shot 可以不同角度：正面 → 微傾 → 正面 → 縮遠
- 推薦工具：Rotato / CleanShot Pro / After Effects mockup template

### 音樂 + 音效

- **配樂**：一首貫穿全片，lo-fi ambient 或 minimal piano
  - 推薦風格：Epidemic Sound 搜 "minimal tech" 或 "warm ambient"
  - Beat drop 對齊 Shot 3 知識圖譜展開
- **音效層**（疊在配樂上）：
  - UI tap：柔和、低頻
  - 卡片滑動：短促 swoosh
  - 圖譜展開：shimmer + sub bass
  - 翻頁：紙張質感，極輕

### Typography（如需加文字）

- 字體：SF Pro Display Light 或 Noto Serif TC
- 出場動畫：fade in + 微上移 20px，duration 0.4s，ease-out
- 消失：fade out，duration 0.3s
- 不超過 5 個中文字 per 出場

### 節奏

```
Shot 1 (7s)  ████████░░░░░░░░░░░░░░░░░░░░░░  查詞（建立情境）
Shot 2 (7s)  ░░░░░░░████████░░░░░░░░░░░░░░░░  翻牌（加速節奏）
Shot 3 (9s)  ░░░░░░░░░░░░░░░██████████░░░░░░  圖譜（高潮，放慢）
Shot 4 (5s)  ░░░░░░░░░░░░░░░░░░░░░░░░█████░░  回到閱讀（收束）
End  (2s)    ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░██  標語
             ─── 建立 ──── 推進 ──── 高潮 ── 收 ─
```

---

## 各平台輸出

| 平台 | 尺寸 | 時長 | 備註 |
|------|------|------|------|
| Instagram Reels | 9:16 1080×1920 | 30s | 原片 |
| Threads | 9:16 | 30s | 原片 |
| App Store Preview | 886×1920 (6.7") | 30s | 移除 mockup frame，全螢幕直出 |
| App Store Preview | 1290×2796 (6.7" 3x) | 30s | 同上，高解析度版 |
