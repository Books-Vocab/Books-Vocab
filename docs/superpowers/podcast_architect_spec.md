# Podcast Architect Agent Spec

## 定位

Architect 是 Book→Podcast 管線的**導演**。接收整本書原文，輸出完整的 Production Plan，指揮下游 Scriptwriter agents 平行生成各集腳本。

## 輸入

| 欄位 | 類型 | 說明 |
|------|------|------|
| `book_text` | string | 完整書籍原文（章節結構保留） |
| `book_metadata` | object | `{ title, author, language, total_chars, chapter_count }` |
| `user_preferences` | object | 可選覆寫：目標集數、每集時長、風格偏好 |

## 輸出：Production Plan

```json
{
  "series": {
    "title": "string — 系列標題",
    "subtitle": "string — 副標題/一句話描述",
    "book_type": "enum: fiction_epic | fiction_mystery | fiction_literary | nonfiction_selfhelp | nonfiction_business | nonfiction_science | nonfiction_biography | nonfiction_technical",
    "language": "string",
    "total_episodes": "int",
    "estimated_total_duration_min": "int",
    "tone": "string — 整體語調指示（e.g. 輕鬆但有深度、懸疑緊湊）",
    "hosts": {
      "host_a": {
        "role": "string — e.g. 好奇的探索者、有見解的提問者",
        "personality": "string — 性格描述",
        "voice_id": "string — TTS voice name"
      },
      "host_b": {
        "role": "string — e.g. 博學的講述者、深入的分析者",
        "personality": "string — 性格描述",
        "voice_id": "string — TTS voice name"
      }
    }
  },
  "analysis": {
    "information_density": "enum: low | medium | high",
    "compression_ratio": "string — e.g. 10:1, 3:1",
    "compression_rationale": "string — 為什麼選這個壓縮比",
    "narrative_structure": "string — 書的敘事結構分析（線性/非線性/模組化/累進式）",
    "key_themes": ["string — 貫穿全書的主題"],
    "audience_assumption": "string — 假設聽眾的背景知識程度"
  },
  "episodes": [
    {
      "ep": "int",
      "title": "string",
      "source_chapters": "string — e.g. ch1-ch3, 或精確段落範圍",
      "source_excerpt_strategy": "enum: full_text | key_passages | summary_plus_quotes",
      "estimated_duration_min": "int",
      "core_thesis": "string — 這集要傳達的一個核心訊息",
      "key_points": ["string — 必須覆蓋的要點，按討論順序排列"],
      "must_quote": ["string — 必須引用的原文金句（含出處）"],
      "opening": {
        "strategy": "enum: cold_open | recap_hook | question | anecdote",
        "hook_from_prev": "string | null — 承接上集的什麼",
        "description": "string — 開場怎麼做"
      },
      "pacing": [
        {
          "segment": "string — 段落描述",
          "treatment": "enum: deep_dive | overview | storytelling | debate | rapid_fire",
          "notes": "string — 特殊指示"
        }
      ],
      "closing": {
        "hook_to_next": "string | null — 留給下集的懸念/預告",
        "takeaway": "string — 聽眾帶走的一句話"
      },
      "scriptwriter_instructions": {
        "read_range": "string — Scriptwriter 必須讀的原文精確範圍",
        "do_not_cover": ["string — 明確排除的內容（避免跨集重複）"],
        "style_override": "string | null — 這集的特殊風格指示",
        "context_from_prev": "string — 前一集結尾的最後幾句（銜接用）"
      }
    }
  ]
}
```

## Architect 判斷邏輯

### Step 1：書籍分類與結構分析

讀完全書後判斷：
- **類型**：小說 vs 非虛構，再細分子類
- **敘事結構**：線性（小說）、模組化（自助書各章獨立）、累進式（教科書層層疊加）
- **資訊密度**：場景描寫多 → 低密度；每段都是論點 → 高密度

### Step 2：壓縮比與集數決策

| 書籍類型 | 資訊密度 | 壓縮比 | 每集時長 | 集數/10萬字 |
|---------|---------|--------|---------|------------|
| 史詩奇幻 | 低 | 8:1 ~ 12:1 | 30-45 min | 10-15 |
| 懸疑推理 | 中 | 6:1 ~ 8:1 | 20-30 min | 8-12 |
| 文學小說 | 中 | 5:1 ~ 8:1 | 25-35 min | 8-10 |
| 自我成長 | 高 | 2:1 ~ 4:1 | 15-25 min | 5-8 |
| 商業策略 | 高 | 3:1 ~ 5:1 | 15-20 min | 4-6 |
| 科普 | 中高 | 3:1 ~ 5:1 | 20-30 min | 5-8 |
| 傳記回憶錄 | 中 | 5:1 ~ 8:1 | 25-35 min | 6-10 |
| 技術教科書 | 高 | 2:1 ~ 3:1 | 15-20 min | 按章 |

口語語速參考：中文 ~200 字/min，英文 ~150 words/min。
甜蜜點：20-30 分鐘/集（完聽率最高）。

### Step 3：切割點選擇

依書籍類型使用不同策略：

**小說類**：
- 以故事弧線轉折點為切割邊界（不是機械式按章切）
- 每集結尾必須卡在懸念點（cliffhanger、角色抉擇、新資訊揭露）
- 多條故事線的書，一集內盡量聚焦一條線，避免切換過多

**非虛構類**：
- 以概念邊界切（一集 = 一個完整概念 + 其支撐論證）
- 相關章節合併（e.g. 原子習慣 ch8-10 都在講「提示」，合成一集）
- 獨立性高的章節不要硬拆

### Step 4：集間連貫設計

- **Hook chain**：每集的 `closing.hook_to_next` 必須被下集的 `opening.hook_from_prev` 承接
- **主題線索**：`analysis.key_themes` 中的主題要在系列中有明確的引入→發展→回收
- **術語一致性**：首次出現的專有名詞要標記在哪一集引入，後續集不重複解釋

### Step 5：Scriptwriter 指令生成

為每集的 `scriptwriter_instructions` 提供：
- **精確的原文範圍**：不是「大概 ch3」，而是「ch3 段落 2 到 ch4 段落 15」
- **排除清單**：其他集已覆蓋或將覆蓋的內容
- **前集尾段**：上一集腳本的最後 2-3 句，讓 scriptwriter 自然銜接
- **風格指示**：這段原文適合什麼處理方式（幽默帶過 vs 嚴肅深入 vs 故事化敘述）

## Source Excerpt Strategy

Architect 為每集決定 Scriptwriter 應該拿到什麼形式的原文：

| 策略 | 適用場景 | 說明 |
|------|---------|------|
| `full_text` | 短章節、關鍵情節 | 完整原文送給 Scriptwriter |
| `key_passages` | 長章節、資訊密集 | Architect 挑選重要段落 + 金句 |
| `summary_plus_quotes` | 超長章節、描寫多 | Architect 寫摘要 + 附關鍵引文 |

這個決策影響下游 token 成本和腳本品質。Architect 應在 context window 允許的範圍內盡量給 `full_text`。

## 約束

- 單集腳本字數上限：6000 字（~30 min）
- 單集腳本字數下限：2000 字（~10 min）
- `user_preferences` 中的指定優先於 Architect 自身判斷
- 不生成腳本內容，只生成規劃。腳本由 Scriptwriter 負責
- 輸出必須是合法 JSON

## 實作備註

- **LLM**：Claude Opus 4.6（1M context），透過 claude-code-gateway（`wordnexus.lol/claude/v1/chat/completions`，OpenAI-compatible）呼叫
- **Context window**：1M tokens 足以吃下大多數書籍全文（~50 萬中文字）
- **成本**：已含在 Claude Max 訂閱內，無額外 per-token 費用
- **可冪等**：同一本書 + 同一 preferences 應產出一致的 plan（temperature=0）
