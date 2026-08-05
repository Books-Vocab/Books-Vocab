# 📚 Books & Vocab

一款整合 AI 輔助學習與知識圖譜同步的 iOS EPUB 閱讀器，專為英文學習者打造。

---

## ✨ 功能亮點

### 📖 高品質 EPUB 閱讀器
- 基於 **Readium Swift Toolkit** 的渲染引擎，支援精準排版
- 目錄 (TOC) 快速跳轉，自動儲存閱讀進度
- **莫蘭迪視覺系統**：三種主題（Light / Sepia / Dark），模擬紙張質感
- 可調整字體系列、字級、行高，並透過 `--vocab-opacity` CSS Variable 即時控制生詞底線透明度
- **收合式 Liquid Glass Header**：閱讀時頭部自動縮合為小圓點，最大化閱讀版面

### 🔤 兩階段 AI 翻譯（Token 成本最佳化）

| 階段 | 觸發方式 | 內容 | Token 成本 |
|------|---------|------|-----------|
| **Phase 1** | 點擊單字 | 精簡翻譯 + 詞性 | ~10 output tokens |
| **音標** | 自動 | IPA 發音 | 0（免費字典 API）|
| **Phase 2** | 手動按 `▼` | 語境解釋（1-2句） | 按需觸發 |

- 已加入生詞庫的單字**直接從本地讀取**，零 API 呼叫

### 📝 離線優先生詞庫（Offline-First）
- **三種高亮狀態**：普通文字 → 選取中（黃色）→ 生詞庫（藍色底線）
- SwiftData 本地持久化為唯一資訊來源 (Single Source of Truth)
- 翻頁不重載：底線渲染透過 JS 注入，設定異動後即時套用

### 🧠 知識圖譜雙向同步（KG Sync）與多帳戶隔離
- 與自架的 **Books & Vocab backend（Knowledge Graph, KG）** 雙向同步生詞
- **沙盒隔離**：支援多設備、多使用者，依據自訂 User ID 將資料完全隔離
- **上傳**：待同步生詞推送至 KG（含新增與刪除操作）。
- **觸發背景處理**：呼叫 `/api/pipeline` 交由伺服器在背景執行（AI Enrichment → Difficulty Tier 標記 → 可選第三方整合），App 即刻返回。
- **增量下載合併 (Incremental Sync)**：App 從 KG 拉取**異動過**的最新卡片，透過背景 SwiftData Context 安全地覆寫本地翻譯、詞性、難易度。
- **孤兒清理**：遠端已物理刪除的卡片，本地在全量同步時會自動移除，保持雙向一致

### 🍎 Apple 系統整合 & 多帳戶認證
- **Google Sign-In**：支援 Google 帳戶登入 & 多設備無縫切換
- **Guest Mode**：未登入時仍可查詞與保存至「待收錄」，支援離線優先體驗
- **多帳戶隔離**：每個帳戶的 SwiftData 與 KG 伺服器資料完全隔離

---

## 🏗️ 系統架構

為了實現「離線即時查詞」卻又具備「與遠端多用戶大腦同步」的特性，我們有一套詳盡的架構。
深入了解前後端整合細節，請參見：[👉 `../docs/sop/architecture.md`](../docs/sop/architecture.md)

```
BooksAndVocab/
├── BooksAndVocabApp.swift       # App 進入點，SwiftData Container 初始化（含遷移容錯）
├── ContentView.swift           # 根視圖，Tab 導航
│
├── Models/
│   ├── VocabularyEntry.swift   # 生詞條目（SwiftData Model，含 KG 同步狀態欄位）
│   ├── Book.swift              # 書籍資料模型（SwiftData）
│   ├── ReaderSettings.swift    # 閱讀器偏好設定（字體、主題、AI 引擎、底線透明度）
│   ├── AppColors.swift         # 莫蘭迪色調全域色盤
│   └── SharedTypes.swift       # 共用型別（KGCard 等）
│
├── Services/
│   ├── TranslationService.swift   # AI 翻譯（後端 API）
│   ├── KGService.swift            # KG 伺服器通訊（health check / batch add / background pipeline / pull & merge）
│   ├── KGService+Dictionary.swift # 字典卡 API（搜尋 / entry / 卡 CRUD / promote）
│   │                              # ※ iOS 不直連字典 provider：授權、快取、上游配額全在 backend
│   └── SpeechService.swift        # 單字朗讀（AVSpeechSynthesizer）
│
├── Views/
│   ├── Bookshelf/
│   │   └── BookshelfView.swift         # 書架頁面，匯入 EPUB
│   ├── Reader/
│   │   ├── ReaderView.swift            # 主閱讀畫面，生詞狀態管理
│   │   ├── ReadiumNavigatorView.swift  # UIKit 橋接 + JS 注入（底線 / 高亮 / 設定）
│   │   ├── TranslationPanel.swift      # 毛玻璃翻譯面板（兩階段）
│   │   └── ReaderSettingsPanel.swift   # 閱讀設定面板（Liquid Glass 樣式）
│   ├── Vocabulary/
│   │   ├── VocabularyListView.swift    # 待收錄生詞清單
│   │   ├── KGVocabView.swift           # 已同步知識庫單字列表
│   │   └── SyncView.swift              # 雙向同步控制台（本地步驟進度 + 背景處理觸發）
│   └── Settings/
│       └── SettingsView.swift          # API Key、KG 伺服器 URL、AI 引擎 設定
│
└── Resources/
    ├── Cormorant Garamond (Regular/Bold/Italic/BoldItalic)  # 襯線字體
    ├── Elms Sans (Regular/Bold/Italic/BoldItalic)           # 無襯線字體
    └── Space Mono (Regular/Bold/Italic/BoldItalic)          # 等寬字體
```

---

## 📦 依賴

| 套件 | 用途 |
|------|------|
| [Readium Swift Toolkit](https://github.com/nicegamer7/readium-swift-toolkit) (v3.7.0) | EPUB 解析與排版 |
| Gemini API (`gemini-flash-lite-latest`) | 雲端 AI 翻譯（低 Token 成本）|
| [Free Dictionary API](https://dictionaryapi.dev/) | IPA 音標（免費，零 Token）|
| Books & Vocab Backend（自架） | 知識圖譜、雲端同步與背景處理後端 |

---

## 🚀 快速開始

### 1. Clone & 開啟專案
```bash
git clone <repo-url>
cd BooksAndVocab
open BooksAndVocab.xcodeproj
```

### 2. 登入帳戶（可選）

**選項 A — Google Sign-In（推薦）**
- App → 設定 → 點擊「Google 登入」按鈕
- 使用 Google 帳號登入，自動綁定 User ID 進行多設備同步

**選項 B — 自訂 User ID**
- App → 設定 → 在「自訂帳號」區塊輸入任意字串（例如 `chen`）
- 此選項適合本地測試或多帳戶隔離

**Guest Mode（不登入）**
- 未登入時，App 仍可正常查詞與保存單字至「待收錄」
- 關閉應用後資料保留在本地，下次啟動時恢復

### 3. 匯入 EPUB
- 書架頁面點擊 `+` 匯入 `.epub` 檔案

### 4. 設定 AI 翻譯引擎

- 前往 [Google AI Studio](https://aistudio.google.com/) 取得免費 API Key
- App → 設定 → 輸入 Gemini API Key

### 5. （可選）連線 KG 伺服器與啟動雙向同步
- App → 設定 → 輸入 KG 伺服器 URL（預設 `http://localhost:8000`）
- 已登入的帳戶自動綁定到該 User ID（Google ID 或自訂密語）
- 前往「同步」頁籤執行首次同步，於後續閱讀時 App 會自動背景同步

---

## ⚙️ 系統需求

| 項目 | 需求 |
|------|------|
| iOS | 17.0+ |
| Xcode | 16+ |
| Swift | 6 |

---

## 📄 License

MIT
