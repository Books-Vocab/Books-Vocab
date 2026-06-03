# Instrumented Iteration — 量測驅動除錯

當靜態推理到不了根因時的主力方法。行為 / 效能 / UI / 動畫 / 時序 / 「感覺怪」這類 bug,**人腦對 SwiftUI 失效粒度、re-render storm、hitch、layout 結算、動畫時序的推理極不可靠**。別猜,量測。

## 何時用(觸發訊號)

- 你推不出機制,或推出來但沒把握。
- **已 patch ≥1 次,使用者回「沒變化 / 一樣」。連兩次 = 立即停止推理,轉量測。**
- 「為什麼會卡 / 為什麼不順 / 為什麼閃」這種需要看「實際每幀發生什麼」才能答的問題。

### 疤(真實,建立紀律)
podcast 捲動/底線優化:先賭「拿掉 `.animation(value:)`」→ 使用者「沒變化」;再賭「`TimelineView(paused:)` 擋住 re-eval」→ 使用者「還是沒變化」。兩次都是**對 SwiftUI 行為的純推理**,兩次都錯。加 log 後一眼看到 `ul.frame(non)` 在換句瞬間飆 500-900/s(穩態 60)——真驅動是「underline 機制被放到每個 bubble 上、換句觸發多趟 settling」,跟我猜的完全無關。**推理在這個領域不可信,量測才是。**

## 迴圈(五步)

1. **Instrument** — 用 `app-log-system.md` 的 PerfLog 加 log。**一條 log 對應一個明確假設**,不是亂撒。
2. **Predict** — 看到真實輸出**之前**,寫下可證偽預測:
   - 精確的**行格式**、出現**次序**、每秒**次數 / 計數**。
   - 一個**成功簽名**(模型成立時長怎樣)。
   - **≥2 個失敗簽名**,每個映射到**具體下一步**(= 決策樹)。
3. **Capture** — 使用者跑 device 把真實 log 貼回(或你自己抓)。在迴圈裡使用者就是量測儀器與驗收者。
4. **Verify** — **逐條**比對真實 vs 預測。全中 → 模型成立,推進。任一不中 → 模型錯,而**那一條不中直接告訴你哪個假設崩**(這就是預測要做成決策樹的理由)。
5. 迭代。每輪只前進一個被證實的格子。

## 讓它嚴謹的鐵則

- **可證偽且具體**:「應該會變順」不是預測。「每個相鄰句界 `gap=0.000`;`projT−mStart ∈ [0,0.08]`」才是。
- **決策樹式 log**:設計成不同 mismatch 指向不同壞掉的假設。內含**自檢欄位**——由建構保證必相等的值(例如「句尾 == 末字尾」),若它不相等,代表 log 本身接錯,先修 log。
- **行為改動 ⊥ 量測**:同一輪別「既改行為又加 log」——mismatch 會無法歸因。**先純量測迭代驗證模型,再行為迭代**。本 session:iteration 1 = 純量 boundary 時間模型 + 一個獨立的 bubble crossfade(各自獨立驗證通道);iteration 2 才動 underline 行為。
- **靜態優先**:能從碼 / 資料定的先定,只在碼真的說不準時才往返 device。本 session 從 `PodcastSubtitleEngine` 靜態釘死「句相鄰、翻轉在末字尾」,但**真實 SRT 到底有沒有 gap** 只能量 → 量到 `gap=0.000` 才敢設計接力。
- **饑餓偵測器(starvation detector)**:留一條**每幀**的 counter(如 `ul.frame` ~60/s)。主線若 stall,這條會**出現缺口**。這是不開 Instruments 就能判「到底有沒有 CPU 掉幀」的手法——counter 在可疑時刻仍穩 = **沒有 stall**,於是「體感卡」是視覺問題不是 CPU。本 session 正是靠這條把整個方向從「修 CPU」翻成「修視覺硬切」。
- **機制 vs 正確性**:log 只能證「引擎在轉」(某 rate 在跳),**證不了「畫對且好看」**。log 全綠後,最終驗收交使用者的眼睛。要分清「`ul.next` 在跳」(機制 ✓)與「進場頭真的畫出來且位置對」(眼睛)。
- **build / 真實 log 凌駕一切推理**:當 review / agent / 你自己的推理說 X,而 build 或 device log 說 ¬X,**以 build / log 為準**。本 session review agent 斬釘截鐵說某行 `StaticString` 三元式不能編譯,綠燈兩次直接打臉——沒去改那個「非 bug」。
- **常駐而非拋棄**:log 是基建不是垃圾。一次建好(PerfLog,DEBUG-gated 零 RELEASE 成本),**留著**,跨多輪優化重用。**修完別把 log 拔掉**——下一個優化點要用。

## 慣用 log 形態(對應 PerfLog)

- **rate counter**:`tick("bucket", "detail")` → console 出 `rate bucket(detail)=N/s`。label 當穩定 bucket key,變動值塞 detail。高頻事件用它(每幀 body、layout pass)。
- **饑餓偵測器**:每幀一個 `tick`,看它在可疑時刻會不會掉拍。
- **狀態 / 邊界 tracer**:`mark("boundary", "<from>-><to> <自檢欄位> <真實未知量>")`,每次狀態轉換印一行。自檢欄位驗 log 接線,真實未知量(gap、延遲)才是要量的。
- **分流變體**:`tick(isCurrent ? "ul.frame" : "ul.next")` 把兩個引擎拆成兩 bucket,一條 trace 看清誰在跑。

## worked example(本 session 的 boundary tracer)

目標:換句底線連續(跨句像跨行)。設計接力前必須先確認句界時間模型。

預測(決策樹):

| 預測 | 失敗簽名 → 下一步 |
|---|---|
| `nEnd == lastW.end`、`mStart == firstW.start`(自檢) | 不等 → log 接錯,先修 log |
| 相鄰句 `gap ≈ 0` | gap 普遍 >0.12 → 有 silence,接力窗口要含 gap |
| `projT − mStart ∈ [0,0.08]`(翻轉延遲) | >0.15 → 翻轉嚴重落後,改吃 projected time |
| `to == from+1` 線性播放 | 跳號/重複 → currentId churn 或 seek |

真實 log 回來:`gap=0.000` 全中、`projT−mStart∈[0.025,0.077]`、自檢全等、出現一筆 `54->65 gap=31.240`(非相鄰 = seek,非反例)。**模型確立**,且「翻轉延遲 ~55ms」這個量到的事實**直接決定**了設計:接力必須吃 projT 逐幀、進場 cell 機制要在翻轉前就存在(`isCurrent || isNext`)。沒量到這個,設計就會錯。

## 反模式

- 撒一堆 log 但沒有事前預測 → 看到一堆數字卻不知道哪個算「對」。
- 預測寫成「應該會更好」這種不可證偽句。
- 一輪同時改行為 + 加 log → 看到變化卻不知是哪個造成。
- log 全綠就宣稱「修好了」——機制綠 ≠ 視覺對,還要過眼睛。
- 修完把 log 拔光,下次從零再來。
