<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - backend/src/kg/
verified_against: 5934cc51
-->
# Card 欄位格式規範

## 欄位說明

| 欄位 | 必填 | 格式 | 範例 |
|------|------|------|------|
| `content` | ✓ | 單詞或片語 | `invoke` |
| `meaning` | ✓ | 中文定義 | `引用法律或祈求` |
| `pos` | | 詞性縮寫 | `v.` `n.` `adj.` `adv.` `prep.` |
| `examples` | | 例句，用 `**word**` 標記目標詞 | `The lawyer **invoked** the law.` |
| `collocations` | | 常見搭配 | `invoke a law` |
| `mode` | | `recognition`（預設）或 `production` | `recognition` |

## Mode 說明

| mode | 方向 | 用途 |
|------|------|------|
| `recognition` | 英→中 | 難詞，只需看懂 |
| `production` | 中→英 (cloze) | 需要會用 |

## Word capture normalization（capture 契約）

選詞存入詞庫時，`content` 會經 **capture-normalize**。此規則為 iOS 與 backend 共有契約，**兩端必須同步**：

| 步驟 | 規則 |
|------|------|
| 1 | NFC 相容映射（`precomposedStringWithCompatibilityMapping` / `unicodedata.normalize`） |
| 2 | 去頭尾空白 |
| 3 | **去尾標點** `.,;:!?`（只削尾，保留詞內 `don't` / `well-known`） |
| 4 | （**僅 backend**）單一 token 句首字母小寫，除非全大寫縮寫或含空白片語 |

- 兩端實作：iOS `ReaderTranslationHandler.normalizeWord`（`ios/BooksBrowser/Views/Reader/ReaderTranslationHandler+Persistence.swift`）／ backend `_clean_content`（`backend/src/kg/vocab_shared.py`）。
- iOS **不**做步驟 4（句首小寫）——本地顯示維持自然大小寫，小寫是 backend dedup 的職責。
- 為何 iOS 需削尾標點：podcast 字幕（UITextView）與 PDF（PDFKit）選取會帶尾標點；EPUB（Readium JS）選取已自行切除。前移到 capture 讓翻譯卡片／詞庫預覽當下即乾淨，不靠 backend 單點兜底。
- 契約測試（同一組 fixture 字串）：iOS `normalizeWord_stripsTrailingSentencePunctuation`／backend `tests/test_capture_normalize_contract.py`。改任一端規則必同步另一端與本表。
- **capture normalize ≠ match normalize**：高亮配對另有更寬鬆規則（小寫＋去頭尾全部標點＋折疊彎撇號），即時套用於頁面與詞庫兩側，見 `PodcastVocabHighlightResolver` 與 EPUB `__markVocabWords`；故 capture 形式改變不影響畫底線配對。

## CSV 匯入格式

```csv
"content","pos","meaning","examples","collocations"
"invoke","v.","引用法律或祈求","The lawyer **invoked** the law.","invoke a law|invoke a right"
"evoke","v.","喚起","The music **evoked** memories.","evoke emotions|evoke memories"
"affect","","影響","The weather will **affect** our plans.",""
```

- 所有欄位用 `"..."` 包裹
- 多值用 `|` 分隔
- 空欄位寫 `""`
- 編碼：UTF-8
