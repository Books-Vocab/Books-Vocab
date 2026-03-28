---
name: debug
description: "Use when encountering any bug, test failure, or unexpected behavior — root cause investigation with parallel hypothesis testing via opus agents."
---

# Debug: 根因優先 + 平行假說驗證

**Iron Law: 找到根因之前不動手修。**

## Phase 1: 根因調查

1. **重現** — 取得精確的錯誤訊息、stack trace、重現步驟
2. **定位** — 錯誤發生在哪個層（iOS / API / DB / infra）
3. **追溯** — 沿 call chain 反向追蹤，找到最初觸發點
4. **確認** — 能解釋「為什麼 X 導致 Y」才算找到根因

## Phase 2: 平行假說驗證（奢侈模式）

當有 2+ 可能假說時，**同時 dispatch opus agent 驗證每個假說**：

```
Agent A → 驗證假說 1（讀相關代碼，寫 repro test）
Agent B → 驗證假說 2（同上）
Agent C → 驗證假說 3（同上）
```

每個 agent 回報：
- 假說是否成立 + 證據
- 若成立：建議修復方案

比串行驗證快 3x。

## Phase 3: 修復

1. 先寫 failing test 重現 bug
2. 跑 test 確認紅
3. 寫最小修復
4. 跑 test 確認綠
5. 回歸驗證：revert fix → 確認 test 再次紅 → restore fix
6. Commit

## 停止條件

3 次修復失敗 → 退一步質疑架構，不要繼續補丁。

## 附屬技巧

- `root-cause-tracing.md` — 沿 call chain 反向追蹤
- `defense-in-depth.md` — 四層驗證讓 bug 結構性不可能
- `condition-based-waiting.md` — 取代 arbitrary timeout 的正確方式
- `find-polluter.sh` — 二分法找出污染其他 test 的兇手

## 禁止

- 看到錯就改（沒確認根因）
- 只加 timeout/retry 當 fix
- 改了就說「should work now」而不跑驗證
