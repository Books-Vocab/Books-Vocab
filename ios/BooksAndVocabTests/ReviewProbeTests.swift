//
//  ReviewProbeTests.swift
//  Books & Vocab Tests
//

import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

// MARK: - Plan parsing

@Suite("ReviewProbeOptions")
struct ReviewProbeOptionsTests {
    private let base = ["-ui-testing"]

    @Test func parsesFlipCount() {
        let plan = ReviewProbeOptions.plan(arguments: base + ["-reviewProbe", "30"])
        #expect(plan?.flipCount == 30)
    }

    /// probe 必須與 fixture seeding 同場啟用 — 沒帶 -ui-testing 一律不啟動，
    /// 擋住「對 live container 真實卡片 submit」的 dev footgun。
    @Test func requiresUITestingFlag() {
        #expect(ReviewProbeOptions.plan(arguments: ["-reviewProbe", "30"]) == nil)
    }

    @Test func absentArgumentMeansInactive() {
        #expect(ReviewProbeOptions.plan(arguments: base + ["-skipWelcome"]) == nil)
        #expect(ReviewProbeOptions.plan(arguments: []) == nil)
    }

    @Test func invalidCountMeansInactive() {
        #expect(ReviewProbeOptions.plan(arguments: base + ["-reviewProbe", "abc"]) == nil)
        #expect(ReviewProbeOptions.plan(arguments: base + ["-reviewProbe", "0"]) == nil)
        #expect(ReviewProbeOptions.plan(arguments: base + ["-reviewProbe", "-5"]) == nil)
        #expect(ReviewProbeOptions.plan(arguments: base + ["-reviewProbe", "501"]) == nil)
        #expect(ReviewProbeOptions.plan(arguments: base + ["-reviewProbe"]) == nil)
    }

    @Test func environmentOverridesCadence() {
        let plan = ReviewProbeOptions.plan(
            arguments: base + ["-reviewProbe", "10"],
            environment: [
                "KG_REVIEW_PROBE_REVEAL_MS": "1200",
                "KG_REVIEW_PROBE_INTERFLIP_MS": "2000",
            ]
        )
        #expect(plan?.revealHold == .milliseconds(1200))
        #expect(plan?.interFlip == .milliseconds(2000))
    }

    /// 兩個 cadence 下限：interFlip ≥ 900ms（settle 視窗 800ms）、
    /// revealHold ≥ 900ms（reveal spring settle 0.85s）— 視窗重疊會污染數據。
    @Test func cadenceOverridesAreClampedAboveSettleWindows() {
        let plan = ReviewProbeOptions.plan(
            arguments: base + ["-reviewProbe", "10"],
            environment: [
                "KG_REVIEW_PROBE_REVEAL_MS": "200",
                "KG_REVIEW_PROBE_INTERFLIP_MS": "200",
            ]
        )
        #expect(plan?.revealHold == .milliseconds(900))
        #expect(plan?.interFlip == .milliseconds(900))
    }

    @Test func rememberAlternatesDeterministically() {
        let plan = ReviewProbePlan.standard(flipCount: 4)
        #expect(plan.remember(at: 0) == true)
        #expect(plan.remember(at: 1) == false)
        #expect(plan.remember(at: 2) == true)
        #expect(plan.remember(at: 3) == false)
    }
}

// MARK: - Driver state machine

@Suite("ReviewProbeDriver")
@MainActor
struct ReviewProbeDriverTests {
    /// 模擬 session：reveal 把卡翻到背面；fling 成功＝前進到下一張（正面）。
    @MainActor
    final class MockSession: ReviewProbeSessionDriving {
        var cardsRemaining: Int
        var showingFront = true
        var revealCalls = 0

        init(cards: Int) { self.cardsRemaining = cards }

        var probeHasCurrentCard: Bool { cardsRemaining > 0 }
        var probeIsShowingFront: Bool { showingFront }
        func probeRevealCurrentCard() {
            revealCalls += 1
            showingFront = false
        }

        func flingSucceeded() {
            cardsRemaining -= 1
            showingFront = true
        }
    }

    private func makeDriver(plan: ReviewProbePlan) -> (ReviewProbeDriver, emitted: () -> [String]) {
        let driver = ReviewProbeDriver(plan: plan)
        nonisolated(unsafe) var lines: [String] = []
        driver.emit = { lines.append($0) }
        driver.sleep = { _ in }
        return (driver, { lines })
    }

    @Test func drivesPlannedFlipsThroughRealFlingHandler() async {
        let session = MockSession(cards: 10)
        let (driver, emitted) = makeDriver(plan: .standard(flipCount: 3))
        var flungDirections: [CGFloat] = []
        driver.flingHandler = { direction, _ in
            flungDirections.append(direction)
            session.flingSucceeded()
            return true
        }

        await driver.run(session: session)

        #expect(driver.flipsCompleted == 3)
        #expect(session.revealCalls == 3)
        // remember 交替 → 方向交替（R=+1, F=-1）
        #expect(flungDirections == [1, -1, 1])
        #expect(emitted().contains("KG_REVIEW_PROBE start flips=3"))
        #expect(emitted().contains("KG_REVIEW_PROBE done flips=3"))
    }

    @Test func stopsWhenDeckExhausted() async {
        let session = MockSession(cards: 2)
        let (driver, emitted) = makeDriver(plan: .standard(flipCount: 5))
        driver.flingHandler = { _, _ in
            session.flingSucceeded()
            return true
        }

        await driver.run(session: session)

        #expect(driver.flipsCompleted == 2)
        #expect(emitted().contains("KG_REVIEW_PROBE done flips=2"))
    }

    @Test func abortsAfterConsecutiveFlingRejections() async {
        let session = MockSession(cards: 10)
        let plan = ReviewProbePlan.standard(flipCount: 5)
        let (driver, emitted) = makeDriver(plan: plan)
        driver.flingHandler = { _, _ in false }

        await driver.run(session: session)

        #expect(driver.flipsCompleted == 0)
        #expect(emitted().contains { $0.hasPrefix("KG_REVIEW_PROBE abort reason=fling_unavailable") })
        #expect(!emitted().contains { $0.hasPrefix("KG_REVIEW_PROBE done") })
    }

    @Test func missingHandlerAbortsInsteadOfSpinning() async {
        let session = MockSession(cards: 10)
        let (driver, emitted) = makeDriver(plan: .standard(flipCount: 5))

        await driver.run(session: session)

        #expect(driver.flipsCompleted == 0)
        #expect(emitted().contains { $0.hasPrefix("KG_REVIEW_PROBE abort") })
    }

    /// .task 被取消（view teardown）的殘缺 run 不可發 done — 發 abort
    /// reason=cancelled，外部 collector 才不會把它當成功。
    @Test func cancelledRunEmitsAbortNotDone() async {
        let session = MockSession(cards: 10)
        let (driver, emitted) = makeDriver(plan: .standard(flipCount: 5))
        driver.flingHandler = { _, _ in
            session.flingSucceeded()
            return true
        }

        let task = Task { await driver.run(session: session) }
        task.cancel()
        await task.value

        #expect(emitted().contains { $0.hasPrefix("KG_REVIEW_PROBE abort reason=cancelled") })
        #expect(!emitted().contains { $0.hasPrefix("KG_REVIEW_PROBE done") })
    }

    /// view re-appear 會重跑 .task — run 必須 idempotent，不可重啟已完成的量測。
    @Test func runIsIdempotentAfterFinish() async {
        let session = MockSession(cards: 10)
        let (driver, emitted) = makeDriver(plan: .standard(flipCount: 2))
        driver.flingHandler = { _, _ in
            session.flingSucceeded()
            return true
        }

        await driver.run(session: session)
        await driver.run(session: session)

        #expect(driver.flipsCompleted == 2)
        #expect(emitted().filter { $0.hasPrefix("KG_REVIEW_PROBE done") }.count == 1)
    }
}

// MARK: - Fixture deck

@Suite("ReviewProbeDeckFixture")
@MainActor
struct ReviewProbeDeckFixtureTests {
    private static var marketingDemoData: Data {
        get throws {
            let url = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent() // BooksAndVocabTests
                .deletingLastPathComponent() // ios
                .deletingLastPathComponent() // repo root
                .appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json")
            return try Data(contentsOf: url)
        }
    }

    @Test func deckIsDeterministicAndSorted() throws {
        try FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let seed = try #require(FixtureDatasetStore.reviewDeckSeed(for: .probe))
            #expect(seed.entries.count == 40)
            #expect(seed.entries.first?.word == "probeword001")
            #expect(seed.entries.last?.word == "probeword040")
            let words = seed.entries.map(\.word)
            #expect(words == words.sorted())
            #expect(Set(words).count == 40)
            #expect(seed.entries.allSatisfy { $0.reviewMode == .recognition })
        }
    }

    @Test func seedingClearsExistingEntriesAndInsertsDeck() throws {
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        let container = try ModelContainer(for: VocabularyEntry.self, configurations: config)
        let stale = VocabularyEntry(
            word: "stale-entry",
            translation: "舊資料",
            context: "should be cleared",
            bookTitle: "Old Book"
        )
        container.mainContext.insert(stale)
        try container.mainContext.save()

        try FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            UITestFixtureSeed.seedTodayReview("deck", into: container)
        }

        let entries = try container.mainContext.fetch(FetchDescriptor<VocabularyEntry>())
        #expect(entries.count == 40)
        #expect(!entries.contains { $0.word == "stale-entry" })
    }
}
