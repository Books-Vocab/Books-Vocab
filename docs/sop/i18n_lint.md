<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ios/
  - ops/
verified_against: f0d37ca4
-->
# i18n Lint

`ops/i18n_lint.sh` 掃描 iOS 字串在地化的回歸風險。

## 模式

| Flag | 行為 |
|------|------|
| `--report`(預設) | 印出 findings,exit 0。本機 ad-hoc 查看用 |
| `--baseline` | 把當前命中數寫入 `ops/i18n_baseline.txt`,當 watermark |
| `--baseline-check` | 對照 baseline,findings 或 `localized_calls` 超過即 fail(CI 用) |
| `--strict` | 任何 finding 即 fail。除 legacy 三項外,額外跑「英文模式漏中文」覆蓋檢查 — 見下方「Strict 覆蓋檢查」 |

## 掃描範圍

1. **Raw Chinese 字面**(Swift 檔):
   `Text("中") / Button("中") / Label("中") / Section("中") / Toggle("中") / Picker("中") / Menu("中") / TextField(".*中") / .navigationTitle("中") / .alert("中") / .confirmationDialog("中") / Text(verbatim: "中") / .accessibilityHint("中") / \b\w*[Tt]oast\w*\.(success|error|info|warning)("中") / reportError("中") / ProgressView("中") / vocabLabelChip(title: "中") / .accessibilityLabel("中")`

   其中 toast 規則用 `\b\w*[Tt]oast\w*\.` 而非寫死 `toastCoordinator.`,因此不只攔 `toastCoordinator.success("中")`,連 local alias(如 `let toast = toastCoordinator` 後的 `toast.error("中")`、或任何名稱含 `toast`/`Toast` 的 receiver)也會命中 — 只要字串含 CJK 才算違規。

2. **Raw Chinese return**(`return "中..."`):
   Enum getter / computed property / function 回傳生 Chinese,例如 `var label: String { case .x: return "中" }`。這類值通常透過變數 reference 進到 UI(`Text(option.label)`),靜態 extractor 看不到 — 此 scanner 直接擋 source。修法:(a)改 `return L10n.string("中")`(同 KGVocabSortOption / AppLanguage 模式),(b)刻意保留(語言自名等)加行內 `// i18n-allow: <reason>`。

3. **Static formatter**(`static let X: DateFormatter | RelativeDateTimeFormatter | NumberFormatter`):
   靜態 formatter 不會跟 `AppLanguage` 變,需走 `LocaleAwareFormatter`。

4. **`.xcstrings` needs_review**:
   `Localizable.xcstrings` 內 `state=needs_review` 且 value 空的 entry。

5. **`.localized` usage 計數**(`localized_calls`,debt watermark):
   掃 Swift 檔內 `.localized` 呼叫數,**不計入 `total`**,而是獨立 watermark。用來追蹤 `.localized`-style 在地化欠債在 review-flip 等 surface 不再增長(只能持平或下降)。

## Baseline 檔格式

`ops/i18n_baseline.txt` 由 `--baseline` 寫入,為 key=value 形式:

```
findings=<total>
localized_calls=<count>
```

`--baseline-check` 讀 `findings=` 與 `localized_calls=` 兩個 watermark,任一超過即 fail。為相容舊格式,若檔案是純整數(無 `findings=` 行),fallback 當成 `findings` watermark,且跳過 `localized_calls` 檢查(直到下次重跑 `--baseline` 升級格式)。

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

## Strict 覆蓋檢查

`--strict` 模式除了 legacy 三項(raw / fmt / xcstrings)外,再跑三項 — 把「英文模式回退到中文」這個 P0 風險靜態擋掉。

| Check | 來源 | 失敗條件 |
|---|---|---|
| A. Key Coverage | `ops/_i18n_extract_keys.py` 抽出的 static key 集 | key 不在 `en.lproj/Localizable.strings` 也不在 `Localizable.stringsdict` |
| B. EN Purity | `en.lproj/Localizable.strings` + `.stringsdict` 所有 value | value 含 CJK Unified Ideographs(`[一-鿿]`) |
| C. Plural Coverage | extractor 輸出的 `plural_keys`(`L10n.format(...)` 呼叫) | en value 含 `%d`/`%lld` 整數規格符,但 `.stringsdict` 沒對應 entry |

### Extractor 掃描範圍

`ops/_i18n_extract_keys.py` 解析三種 call shape:
1. `"<key>".localized`
2. `L10n.string("<key>")`
3. `L10n.format("<key>", ...)`(同時進 `plural_keys` 供 Check C)

加上靜態列舉以下 enum 的 `titleKey: String` 內所有 literal,當成 static key:
- `AppLanguage.titleKey`
- `AppAppearanceMode.titleKey`

> 新增其他 `*.titleKey` enum 時必須把型別名加進 `_i18n_extract_keys.py` 的 `KNOWN_TITLEKEY_TYPES`,否則對應 call site(`enum.titleKey.localized` / `L10n.string(enum.titleKey)`)會落到 `dynamic_unresolved`、coverage check 觸及不到 → 英文模式漏中文重現。

### 限制(誠實標記)

- **變數 `.localized`**(`Text(message.localized)`)無法靜態追蹤,落在 `dynamic_unresolved` 報告區。實際 key 須在上游 callsite 由靜態 literal 提供 — 此 lint 不擋,責任在 code review。
- **隱式 `Text(LocalizedStringKey)`** 目前 codebase 0 處;若未來引入,屬靜態無法解析的盲區。
- **Runtime 組合字串**(server error message 直顯)不在範圍。

### 端到端驗證流程

1. `./ops/i18n_lint.sh --strict` 列出當前所有 missing key + en CJK 污染 + plural 缺項。
2. 補 `en.lproj/Localizable.strings`(及 zh-Hant / zh-Hans / ja / ko 一併翻);plural 案例補 `Localizable.stringsdict`。
3. 重跑 `--strict` 直到 exit 0。
4. 此後英文模式漏中文(在靜態可解析範圍內)= 不可能。

## CI 接線

- Phase 7.1 前:`--baseline-check`(防 legacy 三項回歸)
- Phase 7.1 後:Xcode Run Script Phase `--strict`(零容忍,含上述三項覆蓋檢查)
