---
name: deep-scan
description: "Auto-triggered at conversation start — dispatches 5-7 parallel opus agents to comprehensively scan the project for issues across all dimensions."
user-invocable: true
---

# Deep Scan: 全專案平行深度掃描

每次對話自動觸發。Dispatch 5-7 個 opus agent 同時掃描不同維度，匯總問題清單供使用者挑選處理。

## 觸發條件

- 對話開始時自動執行（由 CLAUDE.md 對話啟動流程觸發）
- 使用者手動 `/deep-scan`

## 掃描維度

同時 dispatch 以下 agent（全部 `model: "opus"`，全部背景執行）：

### Agent 1: Backend API 健康度
```
掃描 backend/src/kg/ 所有 endpoint：
- 每個 endpoint 是否有對應 test
- Error handling 是否完整（正確 HTTP status + 錯誤訊息）
- Input validation 是否存在
- 回報：缺 test 的 endpoint 清單、error handling 缺口、validation 缺口
```

### Agent 2: iOS Code Quality
```
掃描 ios/BooksBrowser/ 所有 View/ViewModel：
- Design system token 違規（raw color/font/spacing/animation）
- 狀態覆蓋（loading/empty/error/success）
- 環境注入方式（是否用 @Environment）
- Preview 覆蓋率
- 回報：違規清單（檔案:行號）、缺少狀態覆蓋的 View、缺 Preview 的 View
```

### Agent 3: Test Coverage 缺口
```
分析 backend/tests/ 和 iOS test targets：
- 哪些模組/檔案完全沒有 test
- 現有 test 是否只測 happy path
- Edge case 覆蓋率
- 回報：未覆蓋模組清單、只有 happy path 的 test 清單
```

### Agent 4: Performance 瓶頸
```
掃描：
- N+1 query patterns（ORM 迴圈內查詢）
- 不必要的 embedding 計算
- Sync 機制的效率（batch vs 逐筆）
- iOS 主線程阻塞風險（heavy computation on main）
- 回報：潛在瓶頸清單 + 嚴重度評估
```

### Agent 5: Security 審計
```
掃描：
- Auth bypass 路徑（未驗證的 endpoint）
- SQL injection / command injection 風險
- CORS 配置
- Token/secret 處理（是否硬編碼、是否安全儲存）
- Rate limiting 覆蓋
- 回報：風險清單 + 嚴重度（Critical/Important/Minor）
```

### Agent 6: Architecture Debt
```
掃描：
- 職責不清的大檔案（>300 行且做多件事）
- 跨層耦合（View 直接碰 DB、API handler 含業務邏輯）
- 重複代碼
- 過時/未使用的代碼
- 回報：債務清單 + 建議重構方向
```

### Agent 7: Data Integrity
```
掃描：
- Sync edge cases（offline → online 衝突處理）
- Migration safety（是否有 rollback 策略）
- 資料一致性（前後端 model 是否對齊）
- 回報：風險點 + 影響範圍
```

## 匯總格式

所有 agent 完成後，匯總為一張表：

```markdown
## Deep Scan Results

| 維度 | Critical | Important | Minor | 首要行動 |
|------|----------|-----------|-------|----------|
| Backend API | 0 | 3 | 5 | 補 /api/vocab/merge test |
| iOS Quality | 2 | 4 | 8 | 修 raw color in CardView |
| Test Coverage | 0 | 6 | 2 | 補 graph API edge cases |
| Performance | 1 | 2 | 3 | 修 N+1 in vocab list |
| Security | 1 | 1 | 4 | 修未驗證的 admin endpoint |
| Architecture | 0 | 3 | 7 | 拆 VocabService |
| Data Integrity | 0 | 2 | 1 | 補 sync conflict handling |

### Critical Issues（必須立即處理）
1. ...
2. ...

### 建議處理順序
1. Security Critical → 2. Performance Critical → 3. iOS token 違規 → ...
```

使用者看完後挑選要處理的項目，直接進 design 或 execute 流程。
