# UI 合規審查

你是 iOS UI 代碼審查員。審查當前分支相對於 main 的所有 Swift 變更，產出違規報告並修復。

## 審查範圍

只審查**本分支相對 main 新增或修改的 .swift 檔案**（不含測試、不含 #Preview 區塊）。

用以下指令取得變更檔案清單：
```
git diff main...HEAD --name-only -- 'ios/**/*.swift'
```

如果上述為空（尚未 commit），改用：
```
git diff --name-only -- 'ios/**/*.swift'
git diff --cached --name-only -- 'ios/**/*.swift'
```

## 審查項目

### A. Localization（最高優先）

1. **Raw 中文字串偵測**
   - 掃描變更檔案中 `Text("中文")`, `Button("中文")`, `Label("中文", ...)`, `title: "中文"`, `message: "中文"`, `placeholder: "中文"` 等模式
   - 排除 `#Preview` 區塊內的所有內容
   - 排除純英文/數字/符號字串
   - 違規 → 改為 `"中文".localized` 或 `L10n.string("中文")`

2. **缺失 .strings key 偵測**
   - 收集所有使用 `.localized` 或 `L10n.string(...)` / `L10n.format(...)` 的 key
   - 比對 `ios/BooksAndVocab/en.lproj/Localizable.strings` 和 `ios/BooksAndVocab/zh-Hant.lproj/Localizable.strings`
   - 缺失的 key → 補入兩個 .strings 檔（en 需要英文翻譯，zh-Hant 用 identity mapping）
   - 同步補入 `ja.lproj`、`ko.lproj`、`zh-Hans.lproj`（值暫用中文原文，標記 TODO）

### B. Design Token

1. **Raw color** — `Color.red`, `Color(red:`, `Color(#`, `#colorLiteral`, `UIColor(` → 用 `AppTheme` / `VocabSkin.Palette` / `AppColors`
2. **Raw font** — `.font(.system(`, `Font.custom(`, `UIFont(` → 用 `AppFonts` / `VocabSkin.Typography`
3. **Raw spacing** — padding/spacing 的 magic number（2, 4, 6, 8 等常見值可忽略；非標準值需標記）
4. **Raw animation** — `.spring(`, `.easeOut(`, `.easeIn(`, `.linear(`, `animation: .default` → 用 `AppMotion`
5. **Raw transition** — `.transition(.opacity)`, `.transition(.slide)` 等 → 用 `AppTransition`

### C. 環境注入

- `AppTheme()` 直接建構 → 應改用 `@Environment(\.appTheme)`
- `VocabSkin()` / `VocabSkin.default` 直接建構 → 應改用 `@Environment(\.vocabSkin)`

## 輸出格式

### 階段一：報告

先輸出違規摘要表：

```
## UI 審查報告

| # | 檔案 | 行 | 類別 | 違規描述 | 建議修復 |
|---|------|-----|------|---------|---------|
| 1 | Path.swift | 42 | L10n | raw 中文 Text("設定") | "設定".localized |
| 2 | Path.swift | 58 | Token | Color.red | AppColors.xxx |
```

- 如果零違規，輸出「✅ 審查通過，無違規」並結束
- L10n 缺失 key 單獨列表

### 階段二：修復

報告輸出後，**直接修復所有違規**：
1. 用 Edit 工具修正 Swift 檔案中的違規
2. 將缺失的 L10n key 補入所有 5 個 .strings 檔（按字母序插入正確位置）
3. 修復完成後跑一次 `./ops/ios_build.sh` 驗證編譯

### 階段三：摘要

```
## 修復摘要
- 修正 N 個違規
- 新增 M 個 L10n key
- 編譯結果：✅ / ❌（附錯誤摘要）
```

## 注意事項

- 讀取 `docs/reference/ui/components.md` 了解可用的 token 和元件名稱
- en.lproj 的英文翻譯要語意準確，不可機翻味太重
- .strings 檔格式：`"key" = "value";`，每行一條，按字母序排列
- 如果某個違規你無法確定最佳修復方式，在報告中標記 `⚠️ 需人工判斷` 而非亂改
