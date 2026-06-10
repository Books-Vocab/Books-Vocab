import Foundation
import UIKit

/// 逐 flip 幀取樣的抽象 — 真實作用 CADisplayLink，測試用 fake。
@MainActor
protocol ReviewProbeGapRecording: AnyObject {
    func start()
    func stop() -> ReviewProbeFlipSummary?
}

/// probe 自有的 CADisplayLink recorder。PerfLog.FrameSampler 整體在
/// `#if DEBUG` 內，Release build 量不到 — 這顆編進所有 config，
/// 只在 probe 模式被建構（production 啟動連物件都不存在）。
@MainActor
final class ReviewProbeFrameRecorder: NSObject, ReviewProbeGapRecording {
    private var link: CADisplayLink?
    private var accumulator = ReviewProbeGapAccumulator()

    func start() {
        link?.invalidate()
        accumulator = ReviewProbeGapAccumulator()
        let link = CADisplayLink(target: self, selector: #selector(onFrame(_:)))
        link.add(to: .main, forMode: .common)
        self.link = link
    }

    func stop() -> ReviewProbeFlipSummary? {
        link?.invalidate()
        link = nil
        return accumulator.summary()
    }

    @objc private func onFrame(_ link: CADisplayLink) {
        accumulator.feed(timestamp: link.timestamp)
    }
}

/// driver 對指標層的最小介面（測試用 spy 驗證呼叫序列）。
@MainActor
protocol ReviewProbeMetricsRecording: AnyObject {
    func startRun()
    func beginFlip(index: Int, remember: Bool)
    func endFlip()
    func cancelFlip()
    func finishRun(aborted: Bool)
}

/// 指標 orchestration：逐 flip 開關 recorder、JSONL 漸進落檔（crash/abort
/// 不丟已寫資料）、結尾聚合。雙通道輸出：
/// - 檔案：`Documents/kg_review_probe.jsonl`（header + flip… + summary）
/// - console marker：`KG_REVIEW_PROBE result=<path>` 與 `summary=<json>`
///   （`devicectl --console` / simctl 收 console 即足夠，檔案是備援）。
@MainActor
final class ReviewProbeMetrics: ReviewProbeMetricsRecording {
    static let fileName = "kg_review_probe.jsonl"

    private let plan: ReviewProbePlan
    private let directory: URL
    private let makeRecorder: @MainActor () -> ReviewProbeGapRecording
    private let emit: (String) -> Void

    private var recorder: ReviewProbeGapRecording?
    private var pendingFlip: (index: Int, remember: Bool)?
    private var flips: [ReviewProbeFlipSummary] = []
    private var fileHandle: FileHandle?

    private var fileURL: URL { directory.appendingPathComponent(Self.fileName) }

    init(
        plan: ReviewProbePlan,
        directory: URL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0],
        makeRecorder: @escaping @MainActor () -> ReviewProbeGapRecording = { ReviewProbeFrameRecorder() },
        emit: @escaping (String) -> Void = { NSLog("%@", $0) }
    ) {
        self.plan = plan
        self.directory = directory
        self.makeRecorder = makeRecorder
        self.emit = emit
    }

    func startRun() {
        // 可重入安全：重置上一輪殘留（舊 handle 未 close 會被覆蓋洩漏；
        // flips 殘留會跨 run 混算）。
        try? fileHandle?.close()
        fileHandle = nil
        flips = []
        pendingFlip = nil
        recorder = nil
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            FileManager.default.createFile(atPath: fileURL.path, contents: nil)
            fileHandle = try FileHandle(forWritingTo: fileURL)
        } catch {
            emit("KG_REVIEW_PROBE metrics_file_error=\(error.localizedDescription)")
        }
        appendLine(header())
    }

    func beginFlip(index: Int, remember: Bool) {
        pendingFlip = (index, remember)
        let recorder = makeRecorder()
        recorder.start()
        self.recorder = recorder
    }

    func endFlip() {
        // 無條件先 stop：CADisplayLink 強持有 target，guard 短路跳過 stop()
        // 會讓 recorder 永不釋放、每幀 callback 永跑（latent leak）。
        let summary = recorder?.stop()
        recorder = nil
        let pending = pendingFlip
        pendingFlip = nil
        guard let pending, let summary else { return }
        flips.append(summary)
        appendLine(flipLine(index: pending.index, remember: pending.remember, summary: summary))
    }

    func cancelFlip() {
        _ = recorder?.stop()
        recorder = nil
        pendingFlip = nil
    }

    func finishRun(aborted: Bool) {
        let summary = ReviewProbeRunSummary.aggregate(
            flips,
            aborted: aborted,
            thermalEnd: Self.thermalStateName()
        )
        let line = summaryLine(summary)
        appendLine(line)
        try? fileHandle?.close()
        fileHandle = nil
        emit("KG_REVIEW_PROBE result=\(fileURL.path)")
        emit("KG_REVIEW_PROBE summary=\(line)")
    }

    // MARK: - 行序列化

    /// snake_case + sortedKeys：行格式 deterministic，jq / Python 直接吃。
    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return encoder
    }()

    private struct HeaderRecord: Codable {
        let type: String
        let schema: Int
        let buildConfig: String
        let osVersion: String
        let lowPowerMode: Bool
        let thermalStart: String
        let planFlips: Int
        let planRevealHoldMs: Int
        let planInterFlipMs: Int
        let startedAt: String
    }

    private struct FlipRecord: Codable {
        let type: String
        let i: Int
        let fb: String
        let frames: Int
        let durMs: Double
        let fps: Double
        let maxGapMs: Double
        let maxGapAtMs: Double
        let stalls: Int
        let hitchMs: Double
        let topGapsMs: [Double]
    }

    private struct SummaryRecord: Codable {
        let type: String
        let n: Int
        let stallsTotal: Int
        let flipsWithStall: Int
        let maxGapP50Ms: Double
        let maxGapP95Ms: Double
        let maxGapMaxMs: Double
        let hitchMsPerS: Double
        let aborted: Bool
        let thermalEnd: String
    }

    private func header() -> String {
        let buildConfig: String
        #if DEBUG
        buildConfig = "debug"
        #else
        buildConfig = "release"
        #endif
        return encodeLine(HeaderRecord(
            type: "header",
            schema: 1,
            buildConfig: buildConfig,
            osVersion: UIDevice.current.systemVersion,
            lowPowerMode: ProcessInfo.processInfo.isLowPowerModeEnabled,
            thermalStart: Self.thermalStateName(),
            planFlips: plan.flipCount,
            planRevealHoldMs: Int(plan.revealHold.totalMilliseconds),
            planInterFlipMs: Int(plan.interFlip.totalMilliseconds),
            startedAt: ISO8601DateFormatter().string(from: Date())
        ))
    }

    private func flipLine(index: Int, remember: Bool, summary: ReviewProbeFlipSummary) -> String {
        encodeLine(FlipRecord(
            type: "flip",
            i: index,
            fb: remember ? "R" : "F",
            frames: summary.frames,
            durMs: summary.durMs,
            fps: summary.fps,
            maxGapMs: summary.maxGapMs,
            maxGapAtMs: summary.maxGapAtMs,
            stalls: summary.stalls,
            hitchMs: summary.hitchMs,
            topGapsMs: summary.topGapsMs
        ))
    }

    private func summaryLine(_ summary: ReviewProbeRunSummary) -> String {
        encodeLine(SummaryRecord(
            type: "summary",
            n: summary.n,
            stallsTotal: summary.stallsTotal,
            flipsWithStall: summary.flipsWithStall,
            maxGapP50Ms: summary.maxGapP50Ms,
            maxGapP95Ms: summary.maxGapP95Ms,
            maxGapMaxMs: summary.maxGapMaxMs,
            hitchMsPerS: summary.hitchMsPerS,
            aborted: summary.aborted,
            thermalEnd: summary.thermalEnd
        ))
    }

    private func encodeLine(_ record: some Codable) -> String {
        guard let data = try? Self.encoder.encode(record),
              let line = String(data: data, encoding: .utf8)
        else { return "{\"type\":\"encode_error\"}" }
        return line
    }

    private func appendLine(_ line: String) {
        guard let handle = fileHandle else { return }
        try? handle.write(contentsOf: Data((line + "\n").utf8))
    }

    private static func thermalStateName() -> String {
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: "nominal"
        case .fair: "fair"
        case .serious: "serious"
        case .critical: "critical"
        @unknown default: "unknown"
        }
    }
}

extension Duration {
    /// Duration → 毫秒（probe 記錄/換算用；components 是 (seconds, attoseconds)）。
    var totalMilliseconds: Double {
        Double(components.seconds) * 1000.0 + Double(components.attoseconds) * 1e-15
    }
}
