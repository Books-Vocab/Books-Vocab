import Foundation

/// 單一 flip 視窗（fling → settle）的幀統計。欄位語意對齊 PerfLog.FrameSampler
/// 的 settle.frames（maxGap / stalls@33ms），數字可與歷史 capture 直接比較；
/// 另加 hitchMs（超出 budget 的累積掉幀時間，budget 自校準支援 ProMotion）。
struct ReviewProbeFlipSummary: Codable, Equatable, Sendable {
    let frames: Int
    let durMs: Double
    let fps: Double
    let maxGapMs: Double
    /// maxGap 結束幀相對視窗起點的 offset（對齊 settle.frames 的 maxGapAt）。
    let maxGapAtMs: Double
    /// gap > 33ms 的幀數 — 與歷史資料同義（@60fps 掉 2 幀）。
    let stalls: Int
    /// Σ max(0, gap − budget)，budget = max(2×median gap, 17ms)：
    /// 60Hz → ~33ms、120Hz → ~17ms，median 自校準當前 refresh rate。
    let hitchMs: Double
    /// 最大的 5 個 gap（診斷分佈尾巴用）。
    let topGapsMs: [Double]
}

/// 餵 CADisplayLink timestamp、產出 flip 統計的純函數核心。
/// 與 CADisplayLink 解耦 — 單元測試直接餵合成 timestamp。
struct ReviewProbeGapAccumulator {
    private var firstTimestamp: TimeInterval?
    private var lastTimestamp: TimeInterval?
    private var gapsMs: [Double] = []
    private var maxGapMs: Double = 0
    private var maxGapAtMs: Double = 0

    mutating func feed(timestamp: TimeInterval) {
        guard let first = firstTimestamp, let last = lastTimestamp else {
            firstTimestamp = timestamp
            lastTimestamp = timestamp
            return
        }
        let gapMs = (timestamp - last) * 1000.0
        gapsMs.append(gapMs)
        if gapMs > maxGapMs {
            maxGapMs = gapMs
            maxGapAtMs = (timestamp - first) * 1000.0
        }
        lastTimestamp = timestamp
    }

    func summary() -> ReviewProbeFlipSummary? {
        guard let first = firstTimestamp, let last = lastTimestamp,
              !gapsMs.isEmpty
        else { return nil }
        let durMs = (last - first) * 1000.0
        let frames = gapsMs.count + 1
        let sorted = gapsMs.sorted()
        let median = sorted[sorted.count / 2]
        let budgetMs = max(2.0 * median, 17.0)
        let hitchMs = gapsMs.reduce(0) { $0 + max(0, $1 - budgetMs) }
        return ReviewProbeFlipSummary(
            frames: frames,
            durMs: durMs,
            fps: durMs > 0 ? Double(frames) / (durMs / 1000.0) : 0,
            maxGapMs: maxGapMs,
            maxGapAtMs: maxGapAtMs,
            stalls: gapsMs.count(where: { $0 > 33.0 }),
            hitchMs: hitchMs,
            topGapsMs: Array(sorted.suffix(5).reversed())
        )
    }
}

/// 整個 run 的聚合 — verdict 用的就是這幾個數字（p50/p95/max/stalls）。
struct ReviewProbeRunSummary: Codable, Equatable, Sendable {
    let n: Int
    let stallsTotal: Int
    let flipsWithStall: Int
    let maxGapP50Ms: Double
    let maxGapP95Ms: Double
    let maxGapMaxMs: Double
    /// Σ hitchMs / Σ durMs × 1000 — 每秒動畫時間中的掉幀毫秒數。
    let hitchMsPerS: Double
    let aborted: Bool
    let thermalEnd: String

    /// nearest-rank percentile（deterministic、無內插）。
    static func aggregate(
        _ flips: [ReviewProbeFlipSummary],
        aborted: Bool,
        thermalEnd: String
    ) -> ReviewProbeRunSummary {
        guard !flips.isEmpty else {
            return ReviewProbeRunSummary(
                n: 0, stallsTotal: 0, flipsWithStall: 0,
                maxGapP50Ms: 0, maxGapP95Ms: 0, maxGapMaxMs: 0,
                hitchMsPerS: 0, aborted: aborted, thermalEnd: thermalEnd
            )
        }
        let maxGaps = flips.map(\.maxGapMs).sorted()
        func percentile(_ p: Double) -> Double {
            let rank = max(1, Int((p * Double(maxGaps.count)).rounded(.up)))
            return maxGaps[rank - 1]
        }
        let totalDurMs = flips.reduce(0) { $0 + $1.durMs }
        let totalHitchMs = flips.reduce(0) { $0 + $1.hitchMs }
        return ReviewProbeRunSummary(
            n: flips.count,
            stallsTotal: flips.reduce(0) { $0 + $1.stalls },
            flipsWithStall: flips.count(where: { $0.stalls > 0 }),
            maxGapP50Ms: percentile(0.5),
            maxGapP95Ms: percentile(0.95),
            maxGapMaxMs: maxGaps.last ?? 0,
            hitchMsPerS: totalDurMs > 0 ? totalHitchMs / totalDurMs * 1000.0 : 0,
            aborted: aborted,
            thermalEnd: thermalEnd
        )
    }
}
