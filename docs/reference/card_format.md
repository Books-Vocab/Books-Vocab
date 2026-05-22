<!-- doc-meta
tier: reference
scope:
  - backend/src/kg
verified_against: 4eaa92b
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
