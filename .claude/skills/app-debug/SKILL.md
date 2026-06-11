---
name: app-debug
description: "Use when encountering any bug, test failure, or unexpected behavior — root cause investigation, measurement-driven iteration for behavioral/perf/UI bugs, and parallel hypothesis testing via opus agents."
user-invocable: true
---

# Debug: 根因優先 + 量測驅動 + 平行假說

**Iron Law 1: 找到根因之前不動手修。**
**Iron Law 2: 推不出根因就量測,別猜。猜了改、改了問使用者「有沒有變」= 在浪費往返。**

## 先分類 bug,決定路徑

| bug 型態 | 路徑 |
|---|---|
| 邏輯 / 呼叫鏈 / 錯誤資料來源(crash、wrong path、stack trace) | **靜態追溯** → `root-cause-tracing.md` |
| 行為 / 效能 / UI / 動畫 / 時序 / 「感覺怪」— 你推不出來,或已 patch ≥1 次而使用者說「沒變化」 | **量測驅動迭代** → `instrumented-iteration.md` + `app-log-system.md` |

SwiftUI 失效粒度、re-render storm、hitch、layout/動畫 glitch 這類,**靜態推理極不可靠**。疤:賭「animation」、賭「paused TimelineView」連兩次落空、使用者連說「沒變化」,直到加 log 量測才抓到真驅動。**患「沒變化」兩次 = 立即停止推理,轉量測。**

## Phase 1: 根因調查

1. **重現** — 精確錯誤訊息 / stack / 重現步驟(效能類:精確到「在哪個操作的哪一刻」)
2. **定位** — 哪一層(iOS / API / DB / infra)
3. **追溯 / 量測** — 邏輯 bug 反向追 call chain;行為 bug 走量測迴圈
4. **確認** — 能解釋「為什麼 X 導致 Y」(行為類:**事前預測命中真實 log**)才算根因

## 量測驅動迴圈(核心,詳見 `instrumented-iteration.md`)

1. **Instrument** — 用 app log system 加 log,一條 log = 一個假設。
2. **Predict** — 看真實輸出**之前**寫下可證偽預測:精確行格式 / 次數 / 次序 + 成功簽名 + **≥2 個失敗簽名,每個映射到下一步**(= 決策樹)。
3. **Capture** — 自己抓,不靠使用者貼:sim 用 `ops/ios_ops.sh logs`;**真機 live(含 debug 級/stdout)用 `ops/ios_device_logs.sh syslog`**,事後撈用 `collect`(.logarchive);debugger 不在場的真機 crash 用 `ops/ios_device_logs.sh pull-crashes --parse`,debugger 在場讀 `/tmp/kg_lldb_forensics/LATEST.txt`。
4. **Verify** — 逐條比對。全中 → 模型成立,前進。任一不中 → 模型錯,**該條不中直接定位**是哪個假設崩。
5. 迭代。

鐵則:**行為改動與量測分離迭代**(同輪都改 → mismatch 無法歸因);**靜態優先**(能從碼/資料定的先定,只在碼真說不準時才往返 device);**build / 真實 log 凌駕任何推理或 agent 宣稱**(疤:review agent 誤判某行不能編譯,被綠燈打臉)。

## Phase 2: 平行假說驗證

2+ 假說時**同時** dispatch opus agent(各讀碼 / 寫 repro / 各自加 log 驗證自己那條),回報「成立與否 + 證據 + 修法」。比串行快 3x。

## Phase 3: 修復(TDD)

failing test 紅 → 最小修復 → 綠 → revert 驗回歸再 restore → commit。幾何 / 純函式類務必**先寫單元測試**(本 session `tailExit`/`headEnter` 即如此)。

## 停止條件

- **推理猜測連 2 次沒中 → 停推理,轉量測。**
- 修復連 3 次失敗 → 退一步質疑架構,別繼續補丁。

## 附屬技巧

- `instrumented-iteration.md` — 量測→假設→預測→驗證 迴圈(行為/效能/UI bug 主力)
- `app-log-system.md` — PerfLog 觀測基建(os.Logger × signpost × rate counter)用法與慣例
- `root-cause-tracing.md` — 沿 call chain 反向追溯(邏輯 bug)
- `defense-in-depth.md` — 四層驗證讓 bug 結構性不可能
- `condition-based-waiting.md` — 取代 arbitrary timeout
- `find-polluter.sh` — 二分法找污染 test 的兇手

## 禁止

- 看到錯就改(沒確認根因)
- **推不出來就猜著改、改完問「有沒有變」而沒有量測佐證**
- **把推理 / agent 宣稱凌駕於 build / 真實 log 之上**
- **修完把 log 拔掉**(它是常駐基建,DEBUG-gated 零 RELEASE 成本,下一輪優化要用)
- log 全綠就宣稱「修好了」(機制綠 ≠ 視覺對,還要過眼睛)
- 只加 timeout/retry 當 fix
- 改了就說「should work now」而不跑驗證
