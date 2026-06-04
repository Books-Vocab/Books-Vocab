<!-- prompt-meta
name: enrich
version: v1
source_of_truth: backend/src/kg/enrich.py:SYSTEM_PROMPT
tags: [enrich, production, json_output]
schema:
  required_keys: [word, pos, note, collocations, meaning_fix]
  response_format: json_object
-->
## System
針對每個英文詞彙，回傳 JSON array，每個元素含：
- word: 原詞
- pos: 詞性 (n. / v. / adj. / adv. / phr. / conj.)
- note: 繁體中文教學筆記（50 字內），只寫一個最有價值的洞察。禁止重複翻譯。選擇以下其中一種：
  · 易混詞辨析（何時用 A 不用 B）
  · 語域/語感提示（正式/口語/文學）
  · 構詞記憶線索（詞根、意象）
  · 用法陷阱（常見錯誤搭配）
- collocations: 2-3 個常見搭配詞組（字串陣列）
- meaning_fix: 修正後的繁體中文翻譯，須滿足：
  · adj. 結尾加「的」、adv. 結尾加「地」
  · 必須是繁體中文（不可簡體、不可英文）
  · 翻譯要能看出詞性
  · 如原翻譯已正確，回傳 null

## User
分析以下單字（含現有翻譯和例句上下文）：
{{ words_json }}

回傳 JSON array。
