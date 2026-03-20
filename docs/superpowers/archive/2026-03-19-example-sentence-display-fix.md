# 例句顯示修復 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修復複習卡例句不顯示目標單字的問題 — JS context 截取改為以單字為中心、iOS 截斷加 stem fallback、radius 估算更保守。

**Architecture:** 三個獨立修改：(1) JS `extractContextFromElement` 改為以 word 位置為中心擷取 ±250 字元；(2) iOS `truncateAroundMarkedWord` 在 exact match 失敗時加 stem fallback；(3) `answerExampleRadius` 的 wordsPerLine 估算從 `/52` 改為 `/62`。

**Tech Stack:** Swift (iOS)、JavaScript (Readium WebView injection)

---

### Task 1: JS context 以點選位置為中心擷取

**Files:**
- Modify: `ios/BooksBrowser/Views/Reader/ReadiumNavigatorJS.swift:419-424`

- [ ] **Step 1: 修改 `extractContextFromElement` 函式**

兩個呼叫點都傳入 `word` 參數（vocabWord 或 wordData.word），函式需要用 word 找到它在 textContent 中的位置，以該位置為中心取 ±250 字元。

```javascript
function extractContextFromElement(startEl, fallbackText) {
    var container = findContextContainer(startEl);
    var fullText = container ? container.textContent : fallbackText;
    if (fullText.length <= 500) return fullText.trim();
    // 以 word 在段落中的位置為中心截取
    var wordPos = fullText.toLowerCase().indexOf(fallbackText.toLowerCase());
    if (wordPos < 0) wordPos = fullText.length / 2;
    var start = Math.max(0, wordPos - 250);
    var end = Math.min(fullText.length, wordPos + fallbackText.length + 250);
    return fullText.substring(start, end).trim();
}
```

注意：`fallbackText` 參數在兩個呼叫點分別是 `vocabWord`（line 507）和 `wordData.text`（line 541）。

- `vocabWord` = `.vocab-word` span 的 textContent（即點擊的單字）→ 適合做 indexOf
- `wordData.text` = 整個 textNode 的 textContent（不是單字本身）→ 需要改用 `wordData.word`

因此需同時修改 line 541 的呼叫：

```javascript
// line 507 (vocab span path) — 不需改，vocabWord 就是要搜尋的字
context: extractContextFromElement(vocabSpan.parentElement, vocabWord)

// line 541 (caret range path) — 改傳 wordData.word 而非 wordData.text
context: extractContextFromElement(wordData.textNode.parentElement, wordData.word)
```

- [ ] **Step 2: 手動驗證**

在 Reader 中找一個長段落，點擊段落後半部的單字。確認翻譯面板顯示的例句包含該單字。

- [ ] **Step 3: Build**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Views/Reader/ReadiumNavigatorJS.swift
git commit -m "ios: fix context extraction to center around tapped word (#191)"
```

---

### Task 2: iOS stem fallback — truncateAroundMarkedWord 找不到字時嘗試 stem match

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/CardRichTextRenderer.swift:214-226`

- [ ] **Step 1: 在 exact match 失敗後加 stem fallback**

在 `truncateAroundMarkedWord` 函式的 `targetWordFallback` 分支中，exact regex 失敗後（line 224 之前），加入 stem match 嘗試：

```swift
// --- 現有程式碼 line 214-224 ---
let esc = NSRegularExpression.escapedPattern(for: fallback)
let pattern = "(?<![\\w\\p{L}])\(esc)(?![\\w\\p{L}])"
if let wordRegex = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive),
   let wordMatch = wordRegex.firstMatch(in: stripped, range: NSRange(location: 0, length: nsStripped.length)) {
    let actualWord = nsStripped.substring(with: wordMatch.range)
    let marked = nsStripped.substring(to: wordMatch.range.location)
        + "**\(actualWord)**"
        + nsStripped.substring(from: wordMatch.range.location + wordMatch.range.length)
    return truncateAroundMarkedWord(marked, radiusWords: radiusWords)
}

// ★ NEW: stem fallback — 取 targetWord 的前 4+ 字元做 prefix match
let stemLength = max(min(fallback.count, 6), 4)
let stem = String(fallback.prefix(stemLength))
let stemEsc = NSRegularExpression.escapedPattern(for: stem)
let stemPattern = "(?<![\\w\\p{L}])\(stemEsc)\\w*(?![\\w\\p{L}])"
if let stemRegex = try? NSRegularExpression(pattern: stemPattern, options: .caseInsensitive),
   let stemMatch = stemRegex.firstMatch(in: stripped, range: NSRange(location: 0, length: nsStripped.length)) {
    let actualWord = nsStripped.substring(with: stemMatch.range)
    let marked = nsStripped.substring(to: stemMatch.range.location)
        + "**\(actualWord)**"
        + nsStripped.substring(from: stemMatch.range.location + stemMatch.range.length)
    return truncateAroundMarkedWord(marked, radiusWords: radiusWords)
}

// targetWord 不在例句中：顯示前 (2*radius+1) 個詞
return truncateLeadingWords(stripped, count: 2 * radiusWords + 1)
```

stem 策略：取 targetWord 前 4-6 字元 + `\w*`，case insensitive。例如 "pastures" → stem "pastu" → matches "pastures", "pasturing", "pastured"。

- [ ] **Step 2: Build**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Components/CardRichTextRenderer.swift
git commit -m "ios: add stem fallback to truncateAroundMarkedWord (#191)"
```

---

### Task 3: answerExampleRadius 估算更保守

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewPresenter+CardContent.swift:234`

- [ ] **Step 1: 調整 wordsPerLine 估算**

```swift
// Before:
let wordsPerLine = max(Int(textWidth / 52), 4)

// After — serif 字體平均字寬偏大，用 62 更貼近實際：
let wordsPerLine = max(Int(textWidth / 62), 4)
```

這讓計算出的 radius 略小，文字不會超出可用的 render 空間。

- [ ] **Step 2: Build**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewPresenter+CardContent.swift
git commit -m "ios: conservative wordsPerLine estimate for review example radius (#191)"
```

---

### Task 4: 整合驗證 & PR

- [ ] **Step 1: Full build**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 2: 開 PR**

```bash
gh pr create --title "ios: fix example sentence display — context centering + stem fallback (#191)" --body "$(cat <<'EOF'
## Summary
- JS context extraction: center ±250 chars around tapped word instead of first 500 chars
- truncateAroundMarkedWord: stem fallback when exact targetWord not found
- answerExampleRadius: more conservative wordsPerLine estimate (52→62)

## Test plan
- [ ] Reader: 長段落後半部點字 → 例句包含該字
- [ ] 複習卡: 確認例句以關鍵字為中心、highlight 正確
- [ ] 複習卡: 確認例句不被 clip 到只剩半個字
EOF
)"
```
