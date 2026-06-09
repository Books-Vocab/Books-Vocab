//
//  ReviewEventBoundaryMigrationTests.swift
//  Books & Vocab Tests
//
//  鎖 review-event pull watermark 的一次性自癒 migration。
//
//  背景：舊版 app 曾把非嚴格 ISO8601 字串（naive / 空格分隔 / 純日期）寫入
//  `kg_review_events_since`。現行後端 review-event pull 以 tz-aware ISO8601 回送
//  cursor 為契約；當 client 持續回送舊壞值，後端 400 → watermark 永不前進 →
//  每次背景同步必 partial fail → 每次回前台彈 toast（死鎖）。
//
//  migration 規則：watermark 必須能被嚴格 ISO8601DateFormatter 解析（乾淨 cursor
//  一律來自後端 isoformat，帶 offset、可選小數秒）。否則清除 → 下次 pull 走全量
//  （冪等、無損：review events 以 event_id 去重 merge）。
//

import Foundation
import Testing
@testable import BooksAndVocab

struct ReviewEventBoundaryMigrationTests {

    // MARK: - 判定：什麼是「乾淨、可回送」的 watermark

    @Test func cleanBoundaryAcceptsServerCursorWithFractionalSeconds() {
        // 後端 _format_timestamp 的典型產物（含微秒 + offset）
        #expect(KGService.isCleanReviewEventBoundary("2026-06-01T10:00:00.232000+00:00"))
    }

    @Test func cleanBoundaryAcceptsServerCursorWithoutFractionalSeconds() {
        // 整秒時 isoformat 不帶小數秒
        #expect(KGService.isCleanReviewEventBoundary("2026-06-01T10:00:00+00:00"))
    }

    @Test func cleanBoundaryAcceptsZSuffix() {
        #expect(KGService.isCleanReviewEventBoundary("2026-06-01T10:00:00Z"))
    }

    @Test func staleBoundaryRejectsSwiftDateDescription() {
        // 舊版疑似寫入的 Swift Date.description 風格（空格分隔 + basic offset）
        #expect(!KGService.isCleanReviewEventBoundary("2026-06-01 10:00:00 +0000"))
    }

    @Test func staleBoundaryRejectsNaiveTimestamp() {
        // 無時區 → 後端能容錯但非乾淨 cursor 格式，清掉重來最穩
        #expect(!KGService.isCleanReviewEventBoundary("2026-06-01T10:00:00"))
    }

    @Test func staleBoundaryRejectsDateOnly() {
        #expect(!KGService.isCleanReviewEventBoundary("2026-06-01"))
    }

    @Test func staleBoundaryRejectsGarbage() {
        #expect(!KGService.isCleanReviewEventBoundary("garbage"))
    }

    // MARK: - Migration 行為

    private func makeDefaults(_ name: String) -> UserDefaults {
        let d = UserDefaults(suiteName: "test.\(name)")!
        d.removePersistentDomain(forName: "test.\(name)")
        return d
    }

    @Test func migrationClearsStaleBoundary() {
        let defaults = makeDefaults("clear-stale")
        defaults.set("2026-06-01 10:00:00 +0000", forKey: KGService.SyncKeys.reviewEventPullBoundary)

        KGService.migrateReviewEventBoundaryIfNeeded(defaults: defaults)

        #expect(defaults.string(forKey: KGService.SyncKeys.reviewEventPullBoundary) == nil)
    }

    @Test func migrationKeepsCleanBoundary() {
        let defaults = makeDefaults("keep-clean")
        let clean = "2026-06-01T10:00:00.232000+00:00"
        defaults.set(clean, forKey: KGService.SyncKeys.reviewEventPullBoundary)

        KGService.migrateReviewEventBoundaryIfNeeded(defaults: defaults)

        #expect(defaults.string(forKey: KGService.SyncKeys.reviewEventPullBoundary) == clean)
    }

    @Test func migrationNoOpWhenAbsent() {
        let defaults = makeDefaults("absent")
        // 無 watermark（首次安裝 / 已 reset）→ 不 crash、維持 nil
        KGService.migrateReviewEventBoundaryIfNeeded(defaults: defaults)
        #expect(defaults.string(forKey: KGService.SyncKeys.reviewEventPullBoundary) == nil)
    }
}
