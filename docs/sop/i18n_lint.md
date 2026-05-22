<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ios/
  - ops/
verified_against: 85f5253
-->
# i18n Lint

`ops/i18n_lint.sh` 掃描 iOS 字串在地化的回歸風險。

## 模式

| Flag | 行為 |
|------|------|
| `--report`(預設) | 印出 findings,exit 0。本機 ad-hoc 查看用 |
| `--baseline` | 把當前命中數寫入 `ops/i18n_baseline.txt`,當 watermark |
| `--baseline-check` | 對照 baseline,findings 超過即 fail(CI 用) |
| `--strict` | 任何 finding 即 fail(Phase 7 後切到此模式) |

## 掃描範圍

1. **Raw Chinese 字面**(Swift 檔):
   `Text("中") / Button("中") / Label("中") / Section("中") / Toggle("中") / Picker("中") / Menu("中") / TextField(".*中") / .navigationTitle("中") / .alert("中") / .confirmationDialog("中") / Text(verbatim: "中") / .accessibilityHint("中")`

2. **Static formatter**(`static let X: DateFormatter | RelativeDateTimeFormatter | NumberFormatter`):
   靜態 formatter 不會跟 `AppLanguage` 變,需走 `LocaleAwareFormatter`。

3. **`.xcstrings` needs_review**:
   `Localizable.xcstrings` 內 `state=needs_review` 且 value 空的 entry。

## 豁免規則 (Exemptions)

### 行內豁免

行尾加註解,顯式宣告該行為合法例外:

```swift
let appName = "Books & Vocab Pro"  // i18n-allow: brand
Text("MPSO 開發者")                 // i18n-allow: proper name
let endpoint = "/api/v1/cards"     // i18n-allow: ASCII-only tech ID
```

### 整檔豁免(僅 formatter 檢測)

檔內**任意位置**含 `// i18n-allow: locale-neutral` 註解,整檔跳過 static-formatter 檢測。
用於 wire-format / 內部 key formatter — 即 Locale 釘在 `en_US_POSIX` 且 format token 為純 ASCII(`yyyy-MM-dd`、`HH:mm:ss`、`yyyyMMdd` 等),輸出刻意 locale-invariant。

```swift
// AppDateFormatters.swift
// i18n-allow: locale-neutral
//   All formatters here pin Locale to en_US_POSIX with ASCII-only tokens.
enum AppDateFormatters {
    static let dayKey: DateFormatter = { ... }()  // "yyyy-MM-dd"
}
```

### 自動豁免

| 觸發條件 | 範圍 | 理由 |
|---|---|---|
| 行內含 `L10n.` 或 `.localized` | raw + fmt | 已走在地化管道 |
| 行內含 `LocaleAwareFormatter` | fmt | 已用 locale-aware helper |
| 行內含 `ISO8601DateFormatter` 宣告 | fmt | wire format,永遠 locale-invariant |
| 行內含 `= AppDateFormatters.<name>` | fmt | 引用中央 locale-neutral helper(自動繼承豁免) |
| 檔名含 `Preview` / `Tests` / `PreviewData` | raw + fmt | 預覽/測試用,不上架 |
| 檔內 `#Preview { ... }` 區塊 | raw | demo only,非 user-facing(由 `ops/_i18n_strip_previews.py` strip) |
| 檔內 `private struct *Preview: View { ... }` | raw | preview 專用 helper struct(由 `ops/_i18n_strip_previews.py` strip) |
| 檔內任意處 `// i18n-allow: locale-neutral` | fmt | 整檔豁免 |

### Preview 排除機制

raw-Chinese scan 在比對前會先把以下兩種區塊 blank 掉(行號保留,所以 `file:line` 仍可定位):

1. `#Preview(...) { ... }` macro body — Swift 5.9+ 預覽宣告
2. `private struct <Name>Preview: View { ... }` — 通常作為 `#Preview` 的 helper container

實作位置:`ops/_i18n_strip_previews.py`。如果預覽程式碼確實會被使用者看到(罕見),改用行內 `// i18n-allow: <reason>` 豁免。

## CI 接線

- Phase 7.1 前:`--baseline-check`(防回歸)
- Phase 7.1 後:Xcode Run Script Phase `--strict`(零容忍)
