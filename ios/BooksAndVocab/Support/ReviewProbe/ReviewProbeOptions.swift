import Foundation

/// Today Review 自主量測 probe 的執行計畫。
///
/// 由 `-reviewProbe <flipCount>` launch argument 啟用（配合 `-ui-testing
/// -seedFixture:todayReview:deck` 注入 deterministic 卡組）。啟用後 app 以
/// `ReviewProbeScene` 為 root，`ReviewProbeDriver` 走「reveal → 評分 fling」
/// 的真實使用者路徑量測翻卡效能。production 安裝無法注入 launch argument，
/// 此 seam 在一般啟動下完全惰性（`ReviewProbeOptions.active == nil`）。
struct ReviewProbePlan: Equatable, Sendable {
    var flipCount: Int
    /// 進場後等首屏/啟動雜訊沉降，再開始量測。
    var warmup: Duration
    /// reveal（翻到背面）後停留時間 — 必須蓋過 reveal spring settle（0.85s），
    /// 避免 reveal.frames 視窗與 fling 視窗重疊。
    var revealHold: Duration
    /// fling 後到下一次 reveal 的間隔 — 必須蓋過 settle.frames 的 800ms 視窗。
    var interFlip: Duration
    /// fling 連續被拒（dismissPhase 非 idle / handler 未註冊）達此數即放棄，
    /// 發 abort marker，不無限空轉。
    var maxConsecutiveFailures: Int
    /// 逐 flip 幀取樣視窗 — 對齊 settle.frames 的 800ms（fling 起算），
    /// 取 850ms 含尾端緩衝。recorder 在 fling 前開、此視窗結束時關。
    var settleWindow: Duration = .milliseconds(850)

    /// fling 成功後：先睡滿取樣視窗（關 recorder），再睡這段補足 interFlip。
    var interFlipRemainder: Duration {
        max(.zero, interFlip - settleWindow)
    }

    static func standard(flipCount: Int) -> ReviewProbePlan {
        ReviewProbePlan(
            flipCount: flipCount,
            warmup: .seconds(2),
            revealHold: .milliseconds(1000),
            interFlip: .milliseconds(1300),
            maxConsecutiveFailures: 8
        )
    }

    /// 評分交替（R, F, R, F…）— deterministic，讓 remembered / forgot 兩條
    /// callback 路徑都被覆蓋，且每次 run 的序列完全相同（跨 build 可比）。
    func remember(at index: Int) -> Bool { index.isMultiple(of: 2) }
}

enum ReviewProbeOptions {
    static let argumentName = "-reviewProbe"
    static let maxFlipCount = 500
    /// settle.frames 取樣窗 800ms；inter-flip 低於此會讓視窗跨 flip 重疊，
    /// 單格數據互相污染 — env override 一律 clamp 到 900ms 以上。
    static let minInterFlipMs = 900

    /// reveal spring settle 0.85s — revealHold override 低於此會讓 reveal 視窗
    /// 疊進 fling 視窗，與 interFlip clamp 同理。
    static let minRevealHoldMs = 900

    static func plan(
        arguments: [String],
        environment: [String: String] = [:]
    ) -> ReviewProbePlan? {
        // 綁 -ui-testing：probe 必須與 fixture seeding 同場啟用。沒有這個 gate，
        // 單帶 -reviewProbe 會對 live container 的真實使用者卡片 submit
        //（SRS 排程 + deferred flush 落 DB）—— dev footgun，直接擋掉。
        guard AppRuntimeOptions.isUITesting(arguments: arguments),
              let idx = arguments.firstIndex(of: argumentName),
              arguments.indices.contains(idx + 1),
              let count = Int(arguments[idx + 1]),
              (1...maxFlipCount).contains(count)
        else { return nil }

        var plan = ReviewProbePlan.standard(flipCount: count)
        if let ms = environment["KG_REVIEW_PROBE_REVEAL_MS"].flatMap(Int.init), ms > 0 {
            plan.revealHold = .milliseconds(max(ms, minRevealHoldMs))
        }
        if let ms = environment["KG_REVIEW_PROBE_INTERFLIP_MS"].flatMap(Int.init), ms > 0 {
            plan.interFlip = .milliseconds(max(ms, minInterFlipMs))
        }
        return plan
    }

    /// 本次啟動的 probe 計畫；一般啟動為 nil。
    @MainActor static let active: ReviewProbePlan? = plan(
        arguments: ProcessInfo.processInfo.arguments,
        environment: ProcessInfo.processInfo.environment
    )
}
