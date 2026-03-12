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

## 2. 加上裝置外框（WithFrame API）

**工具**：[WithFrame](https://withfra.me/shot) — 免費 web API，自動偵測裝置解析度套外框。

### 上傳

```bash
# 上傳截圖，取得 session page URL
response=$(curl -s -F 'file=@screenshot.png' "https://shot.withfra.me/new")
page_url=$(echo "$response" | grep -oE 'https://withfra\.me/s/[^ ]+')
```

- 同一 session 的所有上傳共用同一個 page URL
- 支援指定顏色：`?color=black`

### 下載帶框圖

```bash
# 從 page HTML 提取 S3 下載連結
html=$(curl -s "$page_url")
urls=$(echo "$html" | grep -oE 'https://withframe\.s3[^"]+' | sed 's/&#38;/\&/g' | sort -u)

# 用時間戳配對檔案（每個時間戳可能有多種顏色，取第一個）
url=$(echo "$urls" | grep "at%20HH.MM.SS" | head -1)
curl -s -L -o framed.png "$url"
```

### 支援裝置（截至 2026-03）

iPhone 8 ~ iPhone 16 Pro Max。iPhone 17 Pro Max 與 16 Pro Max 同解析度（1320×2868），可正常使用。

### 注意事項

- S3 連結有效期 24 小時
- 每個時間戳對應多個 UUID = 不同顏色版本
- 帶框後圖片尺寸約 1320×2740（比原圖矮，因外框裁切）

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

| # | 畫面 | 大標題 | 副標題 |
|---|------|--------|--------|
| 1 | 生詞庫列表 | 你的單字，一目了然 | 自動追蹤學習進度，掌握每個單字的熟練狀態 |
| 2 | 複習卡片 | 在原文語境中複習 | 釋義、發音、例句、關聯詞——一張卡片全掌握 |
| 3 | 關聯圖 | 單字不再孤立 | 知識圖譜串起詞彙網絡，越讀越融會貫通 |
| 4 | 閱讀器翻譯 | 閱讀中即查即學 | 輕觸生詞即時翻譯，閱讀不中斷、學習不費力 |

---

## 5. 踩坑紀錄

| 問題 | 原因 | 解法 |
|------|------|------|
| ImageMagick 無法渲染中文字 | brew 版 freetype 不支援 macOS .ttc 系統字型 | 改用 Pillow |
| WithFrame curl 下載到 HTML | API 回傳 session page URL，非直接圖片 | 解析 page HTML 提取 S3 signed URL |
| S3 URL 含 `&#38;` | HTML entity 未轉義 | `sed 's/&#38;/\&/g'` |
| 同一截圖多個 S3 UUID | 不同顏色外框版本 | 用時間戳配對，`head -1` 取第一個 |
| deviceframe (npm) 只到 iPhone X | 套件過時 | 改用 WithFrame |
| fastlane frameit 不支援 16/17 | 開源 issue 尚未合併 | 改用 WithFrame |
