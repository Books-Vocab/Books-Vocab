# App Log System — PerfLog 觀測基建

iOS app 的常駐效能 / 行為觀測門面。**一次建好、長期重用、零 RELEASE 成本**。是 `instrumented-iteration.md` 的工具層。

實作:`ios/BooksAndVocab/Services/PerfLog.swift`(SoT,改前先讀)。

## 三個業界訊號,一個門面

1. **os.Logger / category** — Console.app / Xcode console 可依 subsystem + category 過濾。
2. **OSSignposter intervals** — Instruments 的 os_signpost / Points-of-Interest track 看區間耗時。
3. **Rate counters** — 每幀事件計數,**每秒**彙整成一行 rate,console 不被洪流淹。

## Channels & categories

`PerfLog.<category>`,category 來自 `enum PerfCategory`:`render` `layout` `scroll` `underline` `audio` `sync` `reader` `startup` `general`。不夠就**加 case**(rawValue 即 console category 字串與 `KG_PERF_LOG` token)。

subsystem = `<bundleId>.perf`(預設 `com.wordnexus.BooksBrowser.perf`),與一般 AppLog 隔離。

## API

```swift
// 高頻計數 → 每秒一行 `rate <label>(<detail>)=N/s`。
// label 必須是穩定 literal(當 bucket key);變動值塞 detail。
PerfLog.render.tick("cell.body", isCurrent ? "cur" : "non")
// label 也可用「兩個 literal 的三元式」分流成兩 bucket(合法,各分支各自 coerce 成 StaticString):
PerfLog.underline.tick(isCurrent ? "ul.frame" : "ul.next")

// 一次性事件(Logger.debug + Instruments signpost flag)。狀態 / 邊界時刻用。
PerfLog.underline.mark("boundary", "\(from)->\(to) gap=\(g) ...")

// 包住 body,記 signpost 區間 + 回傳耗時 ms(@discardableResult)。
let (v, ms) = PerfLog.scroll.measure("scrollTo", "id=\(id)") { proxy.scrollTo(id) }

// 跨 scope 的 RAII span(onAppear begin / onDisappear end)。
let span = PerfLog.startup.interval("cold-launch"); /* ... */ span.end()
```

## 開關(免重編)

Xcode scheme ▸ Run ▸ Arguments ▸ Environment Variables:

| 變數 | 效果 |
|---|---|
| `KG_PERF_LOG=all` | DEBUG 預設(未設時全開) |
| `KG_PERF_LOG=off` / `none` | 全關 |
| `KG_PERF_LOG=underline,layout` | 只開指定 category(逗號分隔 rawValue) |
| `KG_PERF_SIGNPOST=1` | RELEASE build 也送 signpost 供 Instruments(console 仍靜音) |

DEBUG 另有 `PerfLog.runtimeCategories`(debug menu live 覆寫,免重啟)。

## 成本與安全

- **RELEASE 零成本**:`tick` 整個 `#if DEBUG` → optimized build 整段 DCE,呼叫點編成 nothing(無 atomic、無 lock、無字串)。訊息走 `@autoclosure` 惰性插值。`mark`/`measure` 在 RELEASE 留一條 `signpostsEnabled`(預設 false)的 runtime 分支,關閉時是一次 bool load。
- **thread-safe**:Logger / Signposter 本身安全;唯一共享可變狀態(rate dict)用 `OSAllocatedUnfairLock`。`tick` 可從任何 thread / actor 呼叫(layout、TimelineView、main-actor body)。

## 在 console 過濾(使用者也能用)

- 依 **subsystem** `…perf` 或 **category**(`underline` / `render` …)。
- 依**訊息子字串**:打 `boundary` 只看邊界 tracer、打 `rate` 只看每秒彙整、打 `ul.frame` 只看那條每幀 counter。
- Xcode console 下方 filter 欄直接輸入子字串即生效;Console.app 用 `subsystem:…perf category:underline`。

## 慣例(本 session 確立,沿用)

- **rate**:label = 穩定 bucket,detail = 變動註記。同一邏輯事件**一個** label,別讓動態值(`n=3`/`n=4`)各成一桶。
- **饑餓偵測器**:某條每幀 `tick` 穩在 ~螢幕更新率;它**掉拍/出缺口**即主線 stall。不開 profiler 就能判 CPU hitch 有無。
- **邊界 tracer**:`mark` 每次狀態轉換一行,含「由建構保證相等」的**自檢欄位**(驗 log 接線)+ 真正要量的**未知量**(延遲、gap)。
- **變體分流**:`tick(cond ? "a" : "b")` 一條 trace 看清兩個並行引擎誰在跑、各跑多快。

## 新增觀測點 checklist

1. 既有 category 夠不夠?不夠就加 `PerfCategory` case。
2. 高頻(每幀/每 layout)→ `tick`;一次性轉換 → `mark`;要耗時 → `measure`/`interval`。
3. label 用穩定 literal,動態塞 detail。
4. 配一條事前**預測**(見 `instrumented-iteration.md`),不是加完就等著看。
5. **留著**,別修完就拔。
