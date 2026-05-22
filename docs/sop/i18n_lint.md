<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ios/
  - ops/
verified_against: d9937c8
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

## 自動豁免

- 行內含 `L10n.` 或 `.localized` → 已走在地化管道
- 行尾 `// i18n-allow: <reason>` → 顯式豁免(品牌名、人名、技術 ID)
- 檔案路徑含 `Preview` / `Tests` / `PreviewData` → 預覽/測試用,不上架

## 加豁免

```swift
let appName = "Books & Vocab Pro"  // i18n-allow: brand
Text("MPSO 開發者")  // i18n-allow: proper name
```

## CI 接線

- Phase 7.1 前:`--baseline-check`(防回歸)
- Phase 7.1 後:Xcode Run Script Phase `--strict`(零容忍)
