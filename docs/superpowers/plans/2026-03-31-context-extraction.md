# Translation Context Extraction — Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 修復 TXT 檔翻譯 422 錯誤，建立多語言 context 擷取的正確架構。
**Architecture:** TXT 分段改 `\n`、JS 用 `Intl.Segmenter` 取代 regex、Backend 截斷防禦。
**Tech Stack:** Swift, JavaScript (Intl.Segmenter), Python/Pydantic

---

### Task 1: TXT→EPUB 分段改為 `\n`

**Files:**
- Modify: `ios/BooksBrowser/Services/EPUBConverter.swift:361-380`

**行為變更說明**：原本用 `\n\n` 分段，段落內 `\n` 變 `<br/>`。新版每個 `\n` 分出獨立 `<p>`。段間距（`<p>` margin）取代行間距（`<br/>`），對詩歌等格式略有視覺差異，但解決了聊天記錄整文件塞進一個 `<p>` 的根本問題。

- [ ] **Step 1: 寫 test 驗證分段行為**
在 Xcode test target 或 backend 適當位置加入手動驗證描述：
- 輸入 LINE 聊天格式（每行 `\n`，無 `\n\n`）→ 驗證產出多個 `<p>`
- 輸入小說格式（`\n\n` 分段）→ 驗證每行仍為獨立 `<p>`

- [ ] **Step 2: 修改 `splitTXTIntoChapters`**

```swift
private func splitTXTIntoChapters(_ text: String, charsPerChapter: Int) -> [String] {
    let lines = text.components(separatedBy: "\n")
    var chapters: [String] = []
    var current = ""

    for line in lines {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { continue }
        let escaped = escapeHTML(trimmed)

        if current.count + escaped.count > charsPerChapter, !current.isEmpty {
            chapters.append(current)
            current = ""
        }
        if !current.isEmpty { current += "\n" }
        current += "<p>\(escaped)</p>"
    }
    if !current.isEmpty { chapters.append(current) }
    if chapters.isEmpty { chapters.append("<p></p>") }
    return chapters
}
```

- [ ] **Step 3: iOS build**
Run: `./ops/ios_build.sh`

- [ ] **Step 4: Commit**

---

### Task 2: JS context 擷取改用 `Intl.Segmenter`

**Files:**
- Modify: `ios/BooksBrowser/Views/Reader/ReadiumNavigatorJS.swift:410-465`

**F2 修正**：`findContextContainer` 不對 `P`/`DIV`/`SECTION` 加大小限制（避免正常 EPUB 長段落被跳過）。只在最終 fallback 到 `BODY` 時用 fullText 長度防護。

**F1 修正**：Fallback regex 簡化，避免重疊匹配。

- [ ] **Step 1: 替換 `findContextContainer` + `extractContextFromElement`**

```javascript
function findContextContainer(startEl) {
    var container = startEl;
    while (container) {
        var tag = (container.tagName || '').toUpperCase();
        if (tag === 'P' || tag === 'LI' || tag === 'BLOCKQUOTE' || tag === 'TD'
            || tag === 'DIV' || tag === 'SECTION') return container;
        if (tag === 'BODY') return container;
        container = container.parentElement;
    }
    return null;
}

function extractContextFromElement(startEl, word) {
    var container = findContextContainer(startEl);
    var fullText = container ? container.textContent : (startEl ? startEl.textContent : word);
    fullText = fullText.trim();

    // Use Intl.Segmenter for locale-aware sentence splitting (Safari 14.1+)
    var sentences;
    if (typeof Intl !== 'undefined' && Intl.Segmenter) {
        var lang = document.documentElement.lang || navigator.language || 'en';
        var segmenter = new Intl.Segmenter(lang, { granularity: 'sentence' });
        sentences = Array.from(segmenter.segment(fullText), function(s) { return s.segment; });
    } else {
        // Fallback: split on CJK/Western sentence terminators and newlines
        sentences = fullText.split(/(?<=[.!?\u3002\uff01\uff1f])\s*|(?<=\n)/);
        sentences = sentences.filter(function(s) { return s.trim().length > 0; });
    }

    if (!sentences || sentences.length <= 1) {
        if (fullText.length <= 300) return fullText;
        var wordPos = fullText.toLowerCase().indexOf(word.toLowerCase());
        if (wordPos < 0) wordPos = Math.floor(fullText.length / 2);
        var start = Math.max(0, wordPos - 150);
        var end = Math.min(fullText.length, wordPos + word.length + 150);
        return fullText.substring(start, end).trim();
    }

    var wordLower = word.toLowerCase();
    var targetIdx = -1;
    for (var i = 0; i < sentences.length; i++) {
        if (sentences[i].toLowerCase().indexOf(wordLower) >= 0) {
            targetIdx = i;
            break;
        }
    }
    if (targetIdx < 0) return fullText.substring(0, 300).trim();

    // Return: previous sentence + target sentence + next sentence
    var from = Math.max(0, targetIdx - 1);
    var to = Math.min(sentences.length, targetIdx + 2);
    var result = '';
    for (var j = from; j < to; j++) {
        result += sentences[j];
    }
    result = result.trim();

    // Hard cap at 500 chars (word-centered)
    if (result.length > 500) {
        var wp = result.toLowerCase().indexOf(wordLower);
        if (wp < 0) wp = Math.floor(result.length / 2);
        var s = Math.max(0, wp - 200);
        var e = Math.min(result.length, wp + word.length + 200);
        result = result.substring(s, e).trim();
    }

    return result;
}
```

- [ ] **Step 2: iOS build**
Run: `./ops/ios_build.sh`

- [ ] **Step 3: Commit**

---

### Task 3: Backend context 防禦

**Files:**
- Modify: `backend/src/kg/api_models.py:135-146` — max_length 降到 1000 + validator 截斷值同步
- Modify: `backend/src/kg/translate_service.py:41` — word-centered 截斷
- Test: `backend/tests/test_translate_service.py` 或 `backend/tests/test_model_validation.py`

- [ ] **Step 1: 寫 failing test**
```python
def test_context_around_word_centers_on_word():
    from kg.translate_service import _context_around_word
    ctx = "A" * 200 + " hello " + "B" * 200
    result = _context_around_word(ctx, "hello", max_len=100)
    assert "hello" in result
    assert len(result) <= 100

def test_context_around_word_short_passthrough():
    from kg.translate_service import _context_around_word
    assert _context_around_word("short context", "short") == "short context"

def test_context_around_word_missing_word():
    from kg.translate_service import _context_around_word
    result = _context_around_word("A" * 500, "missing", max_len=100)
    assert len(result) <= 100
```

- [ ] **Step 2: 跑 test 確認失敗**

- [ ] **Step 3: 修改 TranslateRequest + 加 helper**

`api_models.py` TranslateRequest：
```python
context: str = Field(default="", max_length=1000)
```

`api_models.py` normalize_context validator 截斷值也改 1000：
```python
@field_validator("context", mode="before")
@classmethod
def normalize_context(cls, v: str) -> str:
    if isinstance(v, str):
        v = _normalize_context(v)
        if len(v) > 1000:
            v = v[:1000]
    return v
```

`translate_service.py` 加 helper + 替換 3 個 prompt：
```python
def _context_around_word(context: str, word: str, max_len: int = 300) -> str:
    if len(context) <= max_len:
        return context
    pos = context.lower().find(word.lower())
    if pos < 0:
        return context[:max_len]
    half = (max_len - len(word)) // 2
    start = max(0, pos - half)
    end = min(len(context), pos + len(word) + half)
    return context[start:end].strip()
```

3 個 prompt 的 `req.context[:300]` → `_context_around_word(req.context, req.word)`

- [ ] **Step 4: 跑 test 確認通過 + 全量 regression**

- [ ] **Step 5: Commit**

---

### Task 4: iOS client context cap

**Files:**
- Modify: `ios/BooksBrowser/Services/TranslationService.swift:248`

- [ ] **Step 1: 降 context cap 到 600**
```swift
let trimmedContext = context.count > 600 ? String(context.prefix(600)) : context
```

- [ ] **Step 2: iOS build**

- [ ] **Step 3: Commit**

---

### Task 5: Regression + Deploy + PR

- [ ] Backend tests: `cd backend && python -m pytest tests/ -v`
- [ ] iOS build: `./ops/ios_build.sh`
- [ ] Deploy backend
- [ ] 手動驗證：TXT 檔選詞翻譯成功
- [ ] Push + PR
