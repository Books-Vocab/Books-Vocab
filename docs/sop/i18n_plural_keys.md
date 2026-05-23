<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ios/
  - ops/
verified_against: a706c53
-->
# i18n Plural Keys

走 `L10n.format(_:_:)` 配 `%lld` 引發 Apple `NSStringPluralRuleType` 變化。鍵定義在
各 `ios/BooksBrowser/<lang>.lproj/Localizable.stringsdict`。

## Pipeline

- 呼叫:`L10n.format("<key>", Int64(count))`
- 解析:`L10n.format` → `lookup(key)`(三層 fallback)→ `NSString(format:locale:)`,
  locale-aware plural rule engine 處理 `%#@var@` 展開。
- iOS 17+ 內建 5 種語言的 plural rule(en: one/other,zh-Hant/zh-Hans/ja/ko: other)。

## 既有 keys

| key | en | zh-Hant | zh-Hans | ja | ko |
|-----|----|---------|---------|-----|-----|
| `card_count_plural` | `%lld card` / `%lld cards` | `%lld 張` | `%lld 张` | `%lld 枚` | `%lld 장` |

## 新增 plural key 流程

1. 5 個 `.stringsdict` 都加同一個 key,共用 `NSStringLocalizedFormatKey`
2. `NSStringFormatSpecTypeKey = NSStringPluralRuleType`
3. `NSStringFormatValueTypeKey = lld`(Int64;`%d` + Int 在 64-bit 平台對齊不穩,**禁用**)
4. en 必填 `one` + `other`;CJK 語言通常只需 `other`(無單複數)
5. 呼叫端用 `Int64(value)` 或顯式 `Int64` 變數

## 不適用 plural 的場景

- 純字串內嵌(`"\(count) 集"`)無 locale variation → 走 raw `L10n.string` 或維持 raw 中文 + Phase 6 清除
- 多參數計數(`"%d 詞 · %d 連結"`)plist 不支援單一 key 雙 plural,拆 2 key
