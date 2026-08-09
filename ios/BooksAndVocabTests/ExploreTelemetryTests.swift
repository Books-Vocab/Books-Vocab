//
//  ExploreTelemetryTests.swift
//  Books & Vocab Tests
//
//  Explore（共享牌組庫）telemetry 契約：browse / preview / copy 三段漏斗事件寫進
//  observation store 與 SessionMetrics 聚合，且**不洩漏使用者輸入的搜尋字串**。
//
//  兩個隔離手段，理由都是「這個 change set 自己造出了污染源」：
//  ① 聚合斷言用 `SessionMetrics.makeIsolatedForTesting()` 而非 `.shared` ——
//     `SharedDeckCopyControllerTests` 現在會在 copy 成功/失敗時 track，且
//     `BooksAndVocabTests` 會直接 `SessionMetrics.shared.reset()`，並行跑必然互相歸零。
//  ② observation store 只有 `.shared` 一個實例，沒有逃生口，所以每條斷言都以
//     **本測試獨有的 deckId** 當 marker，並用 `last(where:)` 取最新一筆：
//     `preview(limit:)` 回的是 `suffix(limit)`（時序 oldest→newest），`first(where:)`
//     會撿到同一 window 內別的 suite 更早寫入的同形事件——那會讓斷言在別人的資料上
//     變綠。limit 取滿 store 的 `maxEntries`（200），避免目標被擠出窗口。
//

import Foundation
import Testing
@testable import BooksAndVocab

struct ExploreTelemetryTests {

    /// 掃描 observation store，回傳**最後一筆**含 `marker` 的訊息。
    private func latestMessage(containing marker: String) throws -> String {
        let entries = AppObservationStore.shared.preview(limit: 200).entries
        return try #require(
            entries.last(where: { $0.message.contains(marker) })?.message,
            "no observation entry containing \(marker)"
        )
    }

    /// 本次斷言專屬的 deckId，讓 marker 在共享 store 裡唯一。
    private func uniqueDeckId(_ label: String) -> String {
        "telemetry-\(label)-\(UUID().uuidString)"
    }

    @Test func deckBrowsedEventRecordsCountsWithoutLeakingTheQueryText() async throws {
        // browse 事件沒有 deckId 可當 marker，但 `ExploreView.syncCatalog` 是唯一
        // 發送者且沒有任何單元測試會驅動它，故 deck_count 本身即足以辨識。
        AppAnalytics.track(.deckBrowsed(deckCount: 317, hasQuery: true, isFiltered: false))

        let message = try latestMessage(containing: "event=deck_browsed deck_count=317")
        #expect(message.contains("has_query=true"))
        #expect(message.contains("filtered=false"))
    }

    @Test func deckPreviewedEventCarriesDeckIdAndSampleCount() async throws {
        let deckId = uniqueDeckId("previewed")
        AppAnalytics.track(.deckPreviewed(deckId: deckId, sampleCardCount: 8))

        let message = try latestMessage(containing: "event=deck_previewed deck_id=\(deckId)")
        #expect(message.contains("sample_card_count=8"))
    }

    @Test func deckCopyCompletedEventDistinguishesReplayFromFreshCopy() async throws {
        let deckId = uniqueDeckId("copy-completed")
        AppAnalytics.track(.deckCopyCompleted(
            deckId: deckId,
            cardCount: 55,
            alreadyCopied: true,
            durationMs: 420
        ))

        let message = try latestMessage(containing: "event=deck_copy_completed deck_id=\(deckId)")
        #expect(message.contains("card_count=55"))
        #expect(message.contains("already_copied=true"))
        #expect(message.contains("duration_ms=420"))
    }

    @Test func deckCopyFailedEventIsRecordedAtWarningLevel() async throws {
        let deckId = uniqueDeckId("copy-failed")
        AppAnalytics.track(.deckCopyFailed(deckId: deckId, reason: "offline"))

        let entries = AppObservationStore.shared.preview(limit: 200).entries
        let entry = try #require(entries.last(where: { $0.message.contains("deck_id=\(deckId)") }))
        #expect(entry.message.contains("event=deck_copy_failed"))
        #expect(entry.message.contains("reason=offline"))
        #expect(entry.level == .warning)
    }

    /// preview 段的失敗必須留下紀錄，否則 browse→preview 轉換率分不出「沒人點」
    /// 與「點了但預覽載不出來」——copy 段已經沒有這個盲點（deckCopyFailed）。
    @Test func deckPreviewFailedEventIsRecordedAtWarningLevel() async throws {
        let deckId = uniqueDeckId("preview-failed")
        AppAnalytics.track(.deckPreviewFailed(deckId: deckId, reason: "offline"))

        let entries = AppObservationStore.shared.preview(limit: 200).entries
        let entry = try #require(entries.last(where: { $0.message.contains("deck_id=\(deckId)") }))
        #expect(entry.message.contains("event=deck_preview_failed"))
        #expect(entry.message.contains("reason=offline"))
        #expect(entry.level == .warning)
    }

    @Test func sessionMetricsAggregatesTheExploreFunnel() async throws {
        let metrics = SessionMetrics.makeIsolatedForTesting()

        metrics.record(.deckBrowsed(deckCount: 3, hasQuery: false, isFiltered: false))
        metrics.record(.deckBrowsed(deckCount: 3, hasQuery: true, isFiltered: true))
        metrics.record(.deckPreviewed(deckId: "official-starter-en-zh-core", sampleCardCount: 8))
        metrics.record(.deckPreviewFailed(deckId: "official-exam-core-en-zh", reason: "generic"))
        metrics.record(.deckCopyCompleted(
            deckId: "official-starter-en-zh-core", cardCount: 62, alreadyCopied: false, durationMs: 300
        ))
        metrics.record(.deckCopyFailed(deckId: "official-starter-en-zh-core", reason: "offline"))

        let snapshot = metrics.snapshot()
        #expect(snapshot.deckBrowseCount == 2)
        // preview 與 copy 同一條規格：count = 嘗試數（成功 + 失敗），failures 另計。
        #expect(snapshot.deckPreviewCount == 2)
        #expect(snapshot.deckPreviewFailures == 1)
        #expect(snapshot.deckCopyCount == 2)
        #expect(snapshot.deckCopyFailures == 1)
    }

    @Test func sessionMetricsResetClearsExploreCounters() async throws {
        let metrics = SessionMetrics.makeIsolatedForTesting()

        metrics.record(.deckBrowsed(deckCount: 1, hasQuery: false, isFiltered: false))
        metrics.record(.deckPreviewed(deckId: "official-exam-core-en-zh", sampleCardCount: 5))
        metrics.record(.deckPreviewFailed(deckId: "official-exam-core-en-zh", reason: "unauthorized"))
        metrics.record(.deckCopyCompleted(
            deckId: "official-exam-core-en-zh", cardCount: 56, alreadyCopied: false, durationMs: 120
        ))
        #expect(metrics.snapshot().deckBrowseCount == 1)
        #expect(metrics.snapshot().deckPreviewFailures == 1)

        metrics.reset()
        let cleared = metrics.snapshot()
        #expect(cleared.deckBrowseCount == 0)
        #expect(cleared.deckPreviewCount == 0)
        #expect(cleared.deckPreviewFailures == 0)
        #expect(cleared.deckCopyCount == 0)
        #expect(cleared.deckCopyFailures == 0)
    }

    @Test func exploreEventsDoNotDisturbUnrelatedCounters() async throws {
        let metrics = SessionMetrics.makeIsolatedForTesting()

        metrics.record(.deckBrowsed(deckCount: 9, hasQuery: false, isFiltered: false))
        metrics.record(.deckCopyFailed(deckId: "official-starter-en-zh-core", reason: "generic"))

        let snapshot = metrics.snapshot()
        #expect(snapshot.syncCount == 0)
        #expect(snapshot.translationCount == 0)
        #expect(snapshot.reviewCardsTotal == 0)
    }

    @Test func sessionSummaryIsEmittedForAPreviewOnlySession() async throws {
        // 只逛 Explore 的 session（零翻譯/零同步/零複習）也該留下 summary，否則
        // Release 上線後最常見的 session 形狀在 log 裡是靜默的。用 preview-only
        // 驗證是刻意的——那是 guard 裡最容易被漏掉的那一項。
        let metrics = SessionMetrics.makeIsolatedForTesting()
        metrics.record(.deckPreviewed(deckId: "official-starter-en-zh-core", sampleCardCount: 4))

        let snapshot = metrics.snapshot()
        #expect(snapshot.translationCount == 0)
        #expect(snapshot.syncCount == 0)
        #expect(snapshot.reviewCardsTotal == 0)
        #expect(snapshot.deckBrowseCount == 0)
        #expect(snapshot.deckPreviewCount == 1)

        snapshot.logSummary()
        let message = try latestMessage(containing: "event=session_summary")
        #expect(message.contains("deck_previews=1"))
    }
}
