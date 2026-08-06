//
//  PodcastCatalogSkipTests.swift
//  Books & Vocab Tests
//
//  Podcast 目錄同步的「穩態零 detail 請求」契約。
//
//  舊版對每個 series 各發一次 detail 請求、序列等待：2026-08-06 生產量測，整輪
//  7.55s 的同步裡有 6.08s 在那個迴圈，而四個 series 的資料總量只有約 7 KB。
//  改成用伺服器清單自帶的 `updatedAt` 當內容指紋，只抓變更過的。
//
//  這裡守的是**跳過的判準**，因為那才是會出錯的地方：省太多會讓本機停在半套資料，
//  省太少則整個優化白做。每一條 `needsDetailFetch == true` 的分支都對應一個具體的
//  壞掉情境，逐條釘住。
//

import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct PodcastCatalogSkipTests {

    private static func makeContext() -> ModelContext {
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        let container = try! ModelContainer(
            for: PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self,
            configurations: config
        )
        return ModelContext(container)
    }

    // `nonisolated`：這兩個 factory 只組值型別，不碰 SwiftData。標成 MainActor
    // 隔離（整個 struct 是 @MainActor）會讓它們無法從 `fetchDetailsConcurrently`
    // 的 @Sendable 閉包裡呼叫。
    nonisolated private static func summary(
        id: String = "s1", updatedAt: String? = "2026-06-03T03:35:52+00:00", episodeCount: Int? = 2
    ) -> PodcastSeriesSummary {
        PodcastSeriesSummary(
            id: id, title: id, author: nil, hostNames: nil, color: nil, coverPattern: nil,
            coverImageURL: nil, totalDurationSec: nil, episodeCount: episodeCount, updatedAt: updatedAt
        )
    }

    nonisolated private static func detail(
        id: String = "s1", updatedAt: String? = "2026-06-03T03:35:52+00:00", episodes: Int = 2
    ) -> PodcastSeriesDetail {
        PodcastSeriesDetail(
            id: id, title: id, author: nil, hostNames: nil, color: nil, coverPattern: nil,
            coverImageURL: nil, totalDurationSec: nil,
            episodes: (1...max(1, episodes)).map {
                PodcastEpisodeDetail(
                    episodeNumber: $0, title: "ep\($0)", durationSec: 10,
                    audioAvailable: true, subtitleAvailable: false, subtitleContent: nil
                )
            },
            createdAt: nil, updatedAt: updatedAt
        )
    }

    // MARK: - 跳過判準

    @Test("本機沒有這個 series → 必抓")
    func unknownSeriesIsFetched() {
        #expect(PodcastSyncService.needsDetailFetch(summary: Self.summary(), local: nil))
    }

    @Test("指紋相同且集數對得上 → 跳過（穩態）")
    func unchangedSeriesIsSkipped() {
        let context = Self.makeContext()
        PodcastSyncService.upsertSeries(detail: Self.detail(), context: context)
        let local = PodcastSyncService.localSeriesIndex(context: context)["s1"]

        #expect(local?.remoteUpdatedAt == "2026-06-03T03:35:52+00:00", "upsert 必須把指紋寫下來，否則永遠跳不過")
        #expect(!PodcastSyncService.needsDetailFetch(summary: Self.summary(), local: local))
    }

    @Test("指紋不同 → 必抓")
    func changedFingerprintIsFetched() {
        let context = Self.makeContext()
        PodcastSyncService.upsertSeries(detail: Self.detail(), context: context)
        let local = PodcastSyncService.localSeriesIndex(context: context)["s1"]

        #expect(PodcastSyncService.needsDetailFetch(
            summary: Self.summary(updatedAt: "2026-08-06T00:00:00+00:00"), local: local
        ))
    }

    @Test("伺服器沒給指紋 → 必抓，不能因為「本機有東西」就省")
    func missingFingerprintIsFetched() {
        let context = Self.makeContext()
        PodcastSyncService.upsertSeries(detail: Self.detail(), context: context)
        let local = PodcastSyncService.localSeriesIndex(context: context)["s1"]

        #expect(PodcastSyncService.needsDetailFetch(summary: Self.summary(updatedAt: nil), local: local))
        #expect(PodcastSyncService.needsDetailFetch(summary: Self.summary(updatedAt: ""), local: local))
    }

    @Test("指紋相同但本機集數少了 → 必抓。這是完整性檢查，不是快取檢查")
    func truncatedLocalStateIsRefetched() {
        let context = Self.makeContext()
        // 上一輪只寫了 2 集就被中斷，伺服器其實有 8 集。
        PodcastSyncService.upsertSeries(detail: Self.detail(episodes: 2), context: context)
        let local = PodcastSyncService.localSeriesIndex(context: context)["s1"]

        #expect(PodcastSyncService.needsDetailFetch(summary: Self.summary(episodeCount: 8), local: local),
                "只看指紋的話這個 series 會永遠卡在半套資料")
    }

    @Test("被 tombstone 過的 series 復活時要重抓，才拿得回 episodes")
    func resurrectedSeriesIsFetched() {
        let context = Self.makeContext()
        PodcastSyncService.upsertSeries(detail: Self.detail(), context: context)
        let local = PodcastSyncService.localSeriesIndex(context: context)["s1"]
        local?.isSoftDeleted = true

        #expect(PodcastSyncService.needsDetailFetch(summary: Self.summary(), local: local))
    }

    // MARK: - 併發抓取

    @Test("只抓被點名的那幾個，回傳以 seriesId 為鍵，nil 結果不入表")
    func concurrentFetchReturnsOnlyWhatSucceeded() async {
        let requested = Locked<[String]>([])
        let result = await PodcastSyncService.fetchDetailsConcurrently(
            seriesIds: ["a", "b", "c"]
        ) { id in
            requested.mutate { $0.append(id) }
            return id == "b" ? nil : Self.detail(id: id)
        }

        #expect(Set(requested.value) == ["a", "b", "c"])
        #expect(Set(result.keys) == ["a", "c"], "抓失敗的 series 不得混進 details —— 它會餵給 reconcile 去刪 episode")
        #expect(result["a"]?.id == "a")
    }

    @Test("空清單零請求，這就是穩態")
    func emptyListIssuesNoRequests() async {
        let called = Locked(0)
        let result = await PodcastSyncService.fetchDetailsConcurrently(seriesIds: []) { _ in
            called.mutate { $0 += 1 }
            return Self.detail()
        }
        #expect(called.value == 0)
        #expect(result.isEmpty)
    }

    @Test("併發上限被遵守：同時在飛的不超過 maxConcurrent，但每一個都會跑到")
    func concurrencyIsBounded() async {
        let tracker = ConcurrencyTracker()
        let ids = (1...9).map { "s\($0)" }
        let result = await PodcastSyncService.fetchDetailsConcurrently(
            seriesIds: ids, maxConcurrent: 3
        ) { id in
            await tracker.enter()
            await Task.yield()
            await tracker.leave()
            return Self.detail(id: id)
        }

        #expect(result.count == 9, "滑動視窗不得漏掉任何一個")
        let peak = await tracker.peak
        #expect(peak <= 3, "併發上限被突破：peak=\(peak)")
        #expect(peak > 1, "完全沒有併發的話這個優化沒有生效")
    }
}

private final class Locked<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: T
    init(_ value: T) { storage = value }
    var value: T {
        lock.lock(); defer { lock.unlock() }
        return storage
    }
    func mutate(_ body: (inout T) -> Void) {
        lock.lock(); defer { lock.unlock() }
        body(&storage)
    }
}

private actor ConcurrencyTracker {
    private var inFlight = 0
    private(set) var peak = 0

    func enter() {
        inFlight += 1
        peak = max(peak, inFlight)
    }

    func leave() { inFlight -= 1 }
}
