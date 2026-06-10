//
//  ReviewProbeMetricsTests.swift
//  Books & Vocab Tests
//

import Foundation
import Testing
@testable import BooksAndVocab

// MARK: - Gap accumulator（純函數核心）

@Suite("ReviewProbeGapAccumulator")
struct ReviewProbeGapAccumulatorTests {
    /// 60Hz 完美節奏：無 stall、maxGap ≈ 16.7ms、hitch = 0。
    @Test func perfectCadenceHasNoStallsAndNoHitch() {
        var acc = ReviewProbeGapAccumulator()
        let frame = 1.0 / 60.0
        for i in 0..<60 {
            acc.feed(timestamp: Double(i) * frame)
        }
        let summary = try! #require(acc.summary())
        #expect(summary.frames == 60)
        #expect(summary.stalls == 0)
        #expect(summary.maxGapMs > 16.0 && summary.maxGapMs < 17.5)
        #expect(summary.hitchMs == 0)
        #expect(abs(summary.durMs - 59.0 * frame * 1000.0) < 0.001)
    }

    /// 注入一個 70ms gap：maxGap=70、stalls=1、maxGapAt 指到正確位置、
    /// hitch = 70 − budget（budget = max(2×median, 17) = 33.3）。
    @Test func singleStallIsAttributedAndQuantified() {
        var acc = ReviewProbeGapAccumulator()
        let frame = 1.0 / 60.0
        var t = 0.0
        for i in 0..<30 {
            t = Double(i) * frame
            acc.feed(timestamp: t)
        }
        t += 0.070 // 70ms 停頓
        acc.feed(timestamp: t)
        for i in 1...29 {
            acc.feed(timestamp: t + Double(i) * frame)
        }
        let summary = try! #require(acc.summary())
        #expect(abs(summary.maxGapMs - 70.0) < 0.001)
        #expect(summary.stalls == 1)
        // maxGapAt = gap 結束那一幀相對視窗起點的 offset（29 幀 × 16.7ms + 70ms）
        #expect(abs(summary.maxGapAtMs - (29.0 * frame * 1000.0 + 70.0)) < 0.1)
        let expectedBudget = max(2.0 * frame * 1000.0, 17.0)
        #expect(abs(summary.hitchMs - (70.0 - expectedBudget)) < 0.1)
        #expect(summary.topGapsMs.first == summary.maxGapMs)
    }

    /// 120Hz（ProMotion）節奏下 budget 自校準：16.7ms 的 gap 不算 hitch 雜訊。
    @Test func budgetSelfCalibratesAt120Hz() {
        var acc = ReviewProbeGapAccumulator()
        let frame = 1.0 / 120.0
        for i in 0..<120 {
            acc.feed(timestamp: Double(i) * frame)
        }
        let summary = try! #require(acc.summary())
        #expect(summary.stalls == 0)
        #expect(summary.hitchMs == 0)
    }

    @Test func fewerThanTwoFramesYieldsNoSummary() {
        var acc = ReviewProbeGapAccumulator()
        #expect(acc.summary() == nil)
        acc.feed(timestamp: 0)
        #expect(acc.summary() == nil)
    }
}

// MARK: - Run aggregate（純函數）

@Suite("ReviewProbeRunSummary")
struct ReviewProbeRunSummaryTests {
    private func flip(maxGap: Double, stalls: Int = 0, hitch: Double = 0, dur: Double = 850) -> ReviewProbeFlipSummary {
        ReviewProbeFlipSummary(
            frames: 50, durMs: dur, fps: 60,
            maxGapMs: maxGap, maxGapAtMs: 0,
            stalls: stalls, hitchMs: hitch, topGapsMs: [maxGap]
        )
    }

    @Test func percentilesUseNearestRank() {
        let flips = (1...20).map { flip(maxGap: Double($0)) } // 1..20
        let summary = ReviewProbeRunSummary.aggregate(flips, aborted: false, thermalEnd: "nominal")
        #expect(summary.n == 20)
        #expect(summary.maxGapP50Ms == 10) // ceil(0.5*20)=10th → 10
        #expect(summary.maxGapP95Ms == 19) // ceil(0.95*20)=19th → 19
        #expect(summary.maxGapMaxMs == 20)
    }

    @Test func stallAndHitchTotalsAggregate() {
        let flips = [
            flip(maxGap: 60, stalls: 1, hitch: 30, dur: 1000),
            flip(maxGap: 16, stalls: 0, hitch: 0, dur: 1000),
            flip(maxGap: 70, stalls: 2, hitch: 40, dur: 1000),
        ]
        let summary = ReviewProbeRunSummary.aggregate(flips, aborted: true, thermalEnd: "fair")
        #expect(summary.stallsTotal == 3)
        #expect(summary.flipsWithStall == 2)
        // hitchMsPerS = Σhitch / Σdur × 1000 = 70/3000×1000
        #expect(abs(summary.hitchMsPerS - 70.0 / 3.0) < 0.01)
        #expect(summary.aborted == true)
        #expect(summary.thermalEnd == "fair")
    }

    @Test func emptyRunAggregatesToZeros() {
        let summary = ReviewProbeRunSummary.aggregate([], aborted: true, thermalEnd: "nominal")
        #expect(summary.n == 0)
        #expect(summary.maxGapP95Ms == 0)
        #expect(summary.hitchMsPerS == 0)
    }
}

// MARK: - Metrics orchestration + JSONL sink

@Suite("ReviewProbeMetrics")
@MainActor
struct ReviewProbeMetricsTests {
    /// 假 recorder：回傳預先給定的 flip summary，不碰 CADisplayLink。
    @MainActor
    final class FakeRecorder: ReviewProbeGapRecording {
        var canned: [ReviewProbeFlipSummary]
        var startCalls = 0
        init(canned: [ReviewProbeFlipSummary]) { self.canned = canned }
        func start() { startCalls += 1 }
        func stop() -> ReviewProbeFlipSummary? {
            canned.isEmpty ? nil : canned.removeFirst()
        }
    }

    private func makeSummary(maxGap: Double) -> ReviewProbeFlipSummary {
        ReviewProbeFlipSummary(
            frames: 51, durMs: 850, fps: 60,
            maxGapMs: maxGap, maxGapAtMs: 263,
            stalls: maxGap > 33 ? 1 : 0,
            hitchMs: max(0, maxGap - 33), topGapsMs: [maxGap]
        )
    }

    @Test func writesHeaderFlipsAndSummaryAsJSONL() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("kg-probe-test-\(UUID().uuidString)")
        let recorder = FakeRecorder(canned: [makeSummary(maxGap: 58.2), makeSummary(maxGap: 16.7)])
        nonisolated(unsafe) var emitted: [String] = []
        let metrics = ReviewProbeMetrics(
            plan: .standard(flipCount: 2),
            directory: dir,
            makeRecorder: { recorder },
            emit: { emitted.append($0) }
        )

        metrics.startRun()
        metrics.beginFlip(index: 0, remember: true)
        metrics.endFlip()
        metrics.beginFlip(index: 1, remember: false)
        metrics.endFlip()
        metrics.finishRun(aborted: false)

        let url = dir.appendingPathComponent(ReviewProbeMetrics.fileName)
        let lines = try String(contentsOf: url, encoding: .utf8)
            .split(separator: "\n").map(String.init)
        #expect(lines.count == 4) // header + 2 flips + summary

        let header = try #require(try JSONSerialization.jsonObject(with: Data(lines[0].utf8)) as? [String: Any])
        #expect(header["type"] as? String == "header")
        #expect(header["schema"] as? Int == 1)

        let flip0 = try #require(try JSONSerialization.jsonObject(with: Data(lines[1].utf8)) as? [String: Any])
        #expect(flip0["type"] as? String == "flip")
        #expect(flip0["i"] as? Int == 0)
        #expect(flip0["fb"] as? String == "R")
        #expect(abs((flip0["max_gap_ms"] as? Double ?? 0) - 58.2) < 0.001)

        let runSummary = try #require(try JSONSerialization.jsonObject(with: Data(lines[3].utf8)) as? [String: Any])
        #expect(runSummary["type"] as? String == "summary")
        #expect(runSummary["n"] as? Int == 2)
        #expect(runSummary["stalls_total"] as? Int == 1)

        // console 備援：result 路徑 + summary 內嵌 JSON 都要在 marker 流裡
        #expect(emitted.contains { $0.hasPrefix("KG_REVIEW_PROBE result=") })
        #expect(emitted.contains { $0.hasPrefix("KG_REVIEW_PROBE summary=") })
        #expect(recorder.startCalls == 2)
    }

    /// fling 被拒時 cancelFlip 丟棄該視窗 — 不產生 flip 行。
    @Test func cancelledFlipIsDiscarded() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("kg-probe-test-\(UUID().uuidString)")
        let recorder = FakeRecorder(canned: [makeSummary(maxGap: 20)])
        let metrics = ReviewProbeMetrics(
            plan: .standard(flipCount: 1),
            directory: dir,
            makeRecorder: { recorder },
            emit: { _ in }
        )

        metrics.startRun()
        metrics.beginFlip(index: 0, remember: true)
        metrics.cancelFlip()
        metrics.finishRun(aborted: true)

        let url = dir.appendingPathComponent(ReviewProbeMetrics.fileName)
        let lines = try String(contentsOf: url, encoding: .utf8)
            .split(separator: "\n").map(String.init)
        #expect(lines.count == 2) // header + summary（無 flip 行）
        let runSummary = try #require(try JSONSerialization.jsonObject(with: Data(lines[1].utf8)) as? [String: Any])
        #expect(runSummary["n"] as? Int == 0)
        #expect(runSummary["aborted"] as? Bool == true)
    }
}

// MARK: - Driver × metrics 整合（呼叫序列）

@Suite("ReviewProbeDriverMetrics")
@MainActor
struct ReviewProbeDriverMetricsTests {
    @MainActor
    final class SpyMetrics: ReviewProbeMetricsRecording {
        var calls: [String] = []
        func startRun() { calls.append("startRun") }
        func beginFlip(index: Int, remember: Bool) { calls.append("begin:\(index):\(remember ? "R" : "F")") }
        func endFlip() { calls.append("end") }
        func cancelFlip() { calls.append("cancel") }
        func finishRun(aborted: Bool) { calls.append("finish:\(aborted)") }
    }

    @MainActor
    final class MockSession: ReviewProbeSessionDriving {
        var cardsRemaining: Int
        var showingFront = true
        init(cards: Int) { self.cardsRemaining = cards }
        var probeHasCurrentCard: Bool { cardsRemaining > 0 }
        var probeIsShowingFront: Bool { showingFront }
        func probeRevealCurrentCard() { showingFront = false }
        func flingSucceeded() {
            cardsRemaining -= 1
            showingFront = true
        }
    }

    @Test func happyPathSequencesBeginEndAndFinish() async {
        let session = MockSession(cards: 5)
        let driver = ReviewProbeDriver(plan: .standard(flipCount: 2))
        let spy = SpyMetrics()
        driver.metrics = spy
        driver.emit = { _ in }
        driver.sleep = { _ in }
        driver.flingHandler = { _, _ in
            session.flingSucceeded()
            return true
        }

        await driver.run(session: session)

        #expect(spy.calls == ["startRun", "begin:0:R", "end", "begin:1:F", "end", "finish:false"])
    }

    @Test func rejectedFlingCancelsItsWindow() async {
        let session = MockSession(cards: 5)
        let driver = ReviewProbeDriver(plan: .standard(flipCount: 1))
        let spy = SpyMetrics()
        driver.metrics = spy
        driver.emit = { _ in }
        driver.sleep = { _ in }
        var attempts = 0
        driver.flingHandler = { _, _ in
            attempts += 1
            if attempts == 1 { return false }
            session.flingSucceeded()
            return true
        }

        await driver.run(session: session)

        #expect(spy.calls == ["startRun", "begin:0:R", "cancel", "begin:0:R", "end", "finish:false"])
    }

    @Test func abortMarksFinishAborted() async {
        let session = MockSession(cards: 5)
        let driver = ReviewProbeDriver(plan: .standard(flipCount: 1))
        let spy = SpyMetrics()
        driver.metrics = spy
        driver.emit = { _ in }
        driver.sleep = { _ in }
        driver.flingHandler = { _, _ in false }

        await driver.run(session: session)

        #expect(spy.calls.last == "finish:true")
    }
}
