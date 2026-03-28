---
name: design
description: "Use before any creative work — creating features, building components, adding functionality, or modifying behavior. Takes an idea from brainstorm through spec and plan in one flow."
---

# Design: Idea → Spec → Plan

從模糊想法到可執行 plan 的完整閉環。不再拆成多個 skill 串接。

<HARD-GATE>
設計未經使用者確認前，禁止任何實作行為。
</HARD-GATE>

## Checklist

1. **探索專案脈絡** — 讀相關檔案、docs、recent commits
2. **提供視覺夥伴**（若涉及視覺問題）— 獨立訊息，見 `visual-companion.md`
3. **釐清問題** — 一次一題，理解目的/限制/成功標準
4. **提出 2-3 方案** — 含取捨與推薦
5. **呈現設計** — 依複雜度分段，每段使用者確認
6. **寫 spec** — 存至 `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`，commit
7. **Spec review loop** — dispatch opus spec-document-reviewer（見 `spec-document-reviewer-prompt.md`），最多 3 輪
8. **使用者確認 spec**
9. **寫 plan** — 存至 `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`
10. **Plan review loop** — dispatch opus plan-document-reviewer（見 `plan-document-reviewer-prompt.md`），最多 3 輪
11. **使用者確認 plan** → 交給 `execute` skill

## 設計原則

- 一次一個問題，偏好選擇題
- YAGNI 無情砍
- 在既有 codebase 中遵循既有 pattern
- 每個單元職責單一、介面明確、可獨立理解與測試
- 大範圍需求先拆子專案，每個走獨立 design → execute 週期

## Plan 撰寫規範

### Plan Header

```markdown
# [Feature Name] Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** [一句話]
**Architecture:** [2-3 句]
**Tech Stack:** [關鍵技術]
```

### Task 結構

每個 step 是一個 2-5 分鐘的動作：

````markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

- [ ] **Step 1: 寫 failing test**
```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL

- [ ] **Step 3: 寫最小實作**

- [ ] **Step 4: 跑 test 確認通過**

- [ ] **Step 5: Commit**
````

### 規則
- 精確檔案路徑
- 完整程式碼（不寫「加入驗證」這種模糊描述）
- 精確指令 + 預期輸出
- DRY, YAGNI, TDD, 頻繁 commit

## 終點

Plan 確認後，告知使用者：

> "Plan 已存至 `<path>`。準備好就說「執行」，我會用 execute skill 全力平行實作。"
