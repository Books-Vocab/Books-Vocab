<!-- doc-meta
tier: assets
authority: marketing
update_trigger: app-store-asset-refresh
scope:
  - marketing/
  - ops/screenshots/
-->
# App Store 截圖外框製作 SOP

## 概覽

從 Simulator 截圖到 App Store 上架用的帶外框 + 文案截圖，完整流程。

---

## 1. 取得 Simulator 截圖

```bash
# 方法 A：Simulator 內截圖（⌘S），檔案存到桌面
# 方法 B：CLI
xcrun simctl io booted screenshot ~/Desktop/screenshot.png
```

目前使用機型：**iPhone 17 Pro Max**（1320×2868px）

## 2. 加上裝置外框（本地 iPhone frame 模板）

> ⚠️ **WithFrame web API 已棄用**（2026-07-10）：`shot.withfra.me/new` 封 urllib UA→403、上傳格式從 SOP 記錄的 `POST /new`+`file` 變更→400，外部服務每次 refresh 都可能失效。改用 repo 內 checked-in 的 iPhone 裝置外框模板**本地 Pillow 合成**，完全自足、無外部依賴、可重現。

**工具**：`promotion/screenshots/scripts/frame_catalog_screenshots.py`

**模板 asset**：
- `promotion/screenshots/assets/iphone_frame.png` — 黑鈦邊框 + 動態島 + 透明圓角螢幕開口（RGBA）
- `promotion/screenshots/assets/iphone_frame.json` — 螢幕開口幾何（`screen.left/top/right/bottom/cornerRadius`）
- **重生模板**：`./promotion/screenshots/scripts/gen_iphone_frame.py`（一次性從 `sources/iphone-framed/01_vocab_list.png` 提取黑鈦邊框幾何 + 重繪動態島；改邊框/圓角/動態島調此 script 頂部常數後重跑）

**合成邏輯**：截圖縮放到螢幕開口尺寸（1223×2657）→ 貼進開口位置 → 模板 overlay（邊框/圓角/動態島蓋最上）。輸出帶**手機形狀 alpha** 的 RGBA PNG，供 §3 render 以 alpha 生成手機形狀 drop shadow。

**呼叫**：由 `capture_profile.py` 的 `frame_snapshot_sources` 自動串接（`capture_profile run <profile>`），或獨立跑：

```bash
./promotion/screenshots/scripts/frame_catalog_screenshots.py \
  --shots-json <shots.json> --output-dir <framed dir>
```

### 注意事項

- 截圖必須是 **iPhone portrait**（比例 ~0.461）；非 iPhone portrait 來源 resize 會變形（script stderr warn）。`capture_profile.resolve_shot_artifacts` 已偏好 iPhone portrait 選圖（catalog 同時渲染 iPhone 15 Pro portrait + iPad Pro 11 landscape，需擇前者）。
- 模板尺寸 1320×2740；合成輸出同尺寸，帶手機形狀 alpha。

---

## 3. 渲染文案 + 排版（Pillow）

### 依賴

```bash
pip3 install Pillow  # 需要 11.x+
```

### 字型

| 用途 | 字型 | 位置 | TTC index |
|------|------|------|-----------|
| 大標題（襯線） | Noto Serif CJK TC Bold | `~/Library/Fonts/NotoSerifCJKtc-Bold.otf` | N/A |
| 副標題（黑體） | PingFang TC Medium | 系統 PingFang.ttc | 6 |

PingFang.ttc 路徑（macOS）：
```
/System/Library/AssetsV2/com_apple_MobileAsset_Font7/3419f2a427639ad8c8e139149a287865a90fa17e.asset/AssetData/PingFang.ttc
```

PingFang TTC index 速查：

| Index | Font |
|-------|------|
| 0 | PingFang HK Regular |
| 2 | PingFang TC Regular |
| 6 | PingFang TC Medium |
| 10 | PingFang TC Semibold |

> **注意**：ImageMagick 的 freetype 無法載入 macOS 系統 .ttc 字型，必須用 Pillow。

### App Store 截圖尺寸

| 螢幕 | Portrait | Landscape |
|------|----------|-----------|
| 6.5" | 1242×2688 | 2688×1242 |
| 6.7" | 1284×2778 | 2778×1284 |

iPhone Pro Max 截圖用 **1284×2778**。

### 設計參數（最終版 V3）

```python
TARGET_W, TARGET_H = 1284, 2778
FRAME_W = 1200          # 手機框寬度（原圖 1320 縮放）

# 字型大小
TITLE_SIZE = 92          # 襯線大標
SUB_SIZE   = 38          # 黑體副標

# 顏色
TITLE_COLOR = (20, 20, 20)
SUB_COLOR   = (105, 105, 105)

# 版面配置
TITLE_Y = 150            # 標題起始 Y
SUB_GAP = 30             # 標題→副標間距
PHONE_GAP = 100          # 副標→手機間距
```

### 排版邏輯

```
┌─────────────────────┐
│     150px 上邊距      │
│                     │
│   ■ 大標題（襯線 92pt） │ ← 置中
│     30px gap         │
│   ○ 副標題（黑體 38pt） │ ← 置中
│     100px gap        │
│  ┌─────────────────┐ │
│  │                 │ │
│  │   iPhone 外框    │ │ ← 1200px 寬，置中
│  │   （帶陰影）      │ │
│  │                 │ │
│  │                 │ │
│  └────── ✂ ────────┘ │ ← 底部超出畫布 ~85px
└─────────────────────┘
```

### 設計細節

1. **漸層背景**：上白（255）→ 下微灰（237），避免純白平面感
2. **Drop Shadow**：用 frame 的 alpha channel 生成半透明黑色圖層（opacity 60），偏移 (10, 18)，GaussianBlur radius=35
3. **手機底部溢出**：刻意讓手機框底部超出畫布 ~85px，製造縱深與動態感
4. **文字層次**：襯線體大標 vs 黑體副標，色彩深淺區分主次

### 完整渲染腳本

```python
from PIL import Image, ImageDraw, ImageFont, ImageFilter

TITLE_FONT = ImageFont.truetype(
    "/Users/chenliangyu/Library/Fonts/NotoSerifCJKtc-Bold.otf", 92)
FONT_TTC = ("/System/Library/AssetsV2/com_apple_MobileAsset_Font7/"
    "3419f2a427639ad8c8e139149a287865a90fa17e.asset/AssetData/PingFang.ttc")
SUB_FONT = ImageFont.truetype(FONT_TTC, 38, index=6)

TARGET_W, TARGET_H = 1284, 2778
FRAME_W = 1200

copies = [
    ("01_vocab_list",  "你的單字，一目了然",  "自動追蹤學習進度，掌握每個單字的熟練狀態"),
    ("02_review_card", "在原文語境中複習",    "釋義、發音、例句、關聯詞——一張卡片全掌握"),
    ("03_other",       "單字不再孤立",        "知識圖譜串起詞彙網絡，越讀越融會貫通"),
    ("04_reader",      "閱讀中即查即學",      "輕觸生詞即時翻譯，閱讀不中斷、學習不費力"),
]

TITLE_COLOR = (20, 20, 20)
SUB_COLOR   = (105, 105, 105)

for fname, title, subtitle in copies:
    frame = Image.open(f"{fname}.png").convert("RGBA")
    ratio = FRAME_W / frame.width
    new_h = int(frame.height * ratio)
    frame = frame.resize((FRAME_W, new_h), Image.LANCZOS)

    # 漸層背景
    canvas = Image.new("RGBA", (TARGET_W, TARGET_H), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    for y in range(TARGET_H):
        gray = int(255 - (y / TARGET_H) * 18)
        draw.line([(0, y), (TARGET_W, y)], fill=(gray, gray, gray, 255))

    draw = ImageDraw.Draw(canvas)

    # 文字
    tb = draw.textbbox((0, 0), title, font=TITLE_FONT)
    sb = draw.textbbox((0, 0), subtitle, font=SUB_FONT)
    title_w, title_h = tb[2] - tb[0], tb[3] - tb[1]
    sub_w = sb[2] - sb[0]

    title_y = 150
    sub_y = title_y + title_h + 30
    draw.text(((TARGET_W - title_w) // 2, title_y), title,
              font=TITLE_FONT, fill=TITLE_COLOR)
    draw.text(((TARGET_W - sub_w) // 2, sub_y), subtitle,
              font=SUB_FONT, fill=SUB_COLOR)

    # 手機框
    frame_x = (TARGET_W - FRAME_W) // 2
    frame_y = sub_y + 100

    # Drop shadow
    shadow_base = Image.new("RGBA", (TARGET_W, TARGET_H + 200), (0, 0, 0, 0))
    frame_alpha = frame.split()[3]
    shadow_color = Image.new("RGBA", frame.size, (0, 0, 0, 60))
    shadow_color.putalpha(frame_alpha)
    shadow_base.paste(shadow_color, (frame_x + 10, frame_y + 18))
    shadow_base = shadow_base.filter(ImageFilter.GaussianBlur(radius=35))
    canvas = Image.alpha_composite(canvas, shadow_base.crop((0, 0, TARGET_W, TARGET_H)))

    # 貼手機（超出部分裁切）
    phone_layer = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
    paste_h = min(new_h, TARGET_H - frame_y)
    if paste_h > 0:
        cropped_frame = frame.crop((0, 0, FRAME_W, paste_h))
        phone_layer.paste(cropped_frame, (frame_x, frame_y), cropped_frame)
    canvas = Image.alpha_composite(canvas, phone_layer)

    canvas.convert("RGB").save(f"final_{fname}.png", "PNG")
```

---

## 4. 文案清單

App Store 5 張的定調文案（標題/副標）= `ops/capture_profiles/marketing_account.json` 的 `shots[].copy`（**SoT，勿在此複述**）：`knowledge_graph → vocab_list → notebook → stats → today_review`，前 3 張知識網絡/文學情感 hook、後 2 張效率/記憶科學。改文案改 profile，`capture_profile run` 自動疊上。

> 歷史（milestone-4 前的舊 4 張，已被上述 5 張取代）：生詞庫列表 / 複習卡片 / 關聯圖 / 閱讀器翻譯。

---

## 5. 踩坑紀錄

| 問題 | 原因 | 解法 |
|------|------|------|
| ImageMagick 無法渲染中文字 | brew 版 freetype 不支援 macOS .ttc 系統字型 | 改用 Pillow |
| WithFrame web API 已死（2026-07-10） | 封 urllib UA→403、上傳格式從 `POST /new`+`file` 變更→400，外部 SPA 逆向不可靠 | 改本地 iPhone frame 模板合成（§2）；原 WithFrame 坑（S3 URL entity、多 UUID 顏色版）皆已無關 |
| deviceframe (npm) 只到 iPhone X | 套件過時 | 改本地模板合成 |
| fastlane frameit 不支援 16/17 | 開源 issue 尚未合併 | 改本地模板合成 |
