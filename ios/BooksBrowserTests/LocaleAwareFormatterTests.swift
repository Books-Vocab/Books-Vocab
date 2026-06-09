//
//  LocaleAwareFormatterTests.swift
//  Books & Vocab Tests
//

import Foundation
import Testing
@testable import BooksBrowser

// .serialized: tests mutate AppLanguageStore.shared singleton.
@Suite(.serialized)
@MainActor
struct LocaleAwareFormatterTests {

    @Test func test_string_from_template_follows_AppLanguage() async throws {
        let store = AppLanguageStore.shared
        let date = Date(timeIntervalSince1970: 1_716_336_000) // 2024-05-22 (arbitrary)

        store.setLanguage(.japanese)
        let ja = LocaleAwareFormatter.shared.string(from: date, template: "yMMMM")

        store.setLanguage(.english)
        let en = LocaleAwareFormatter.shared.string(from: date, template: "yMMMM")

        defer { store.setLanguage(.system) }
        #expect(ja != en, "ja=\(ja) should differ from en=\(en)")
        #expect(ja.contains("月"), "expected Japanese month output, got: \(ja)")
    }

    @Test func test_string_from_fixed_format_uses_pattern_verbatim() async throws {
        let store = AppLanguageStore.shared
        store.setLanguage(.english)
        defer { store.setLanguage(.system) }

        let date = Date(timeIntervalSince1970: 0)
        let s = LocaleAwareFormatter.shared.string(from: date, format: "yyyy-MM-dd")
        #expect(s == "1970-01-01")
    }

    @Test func test_relativeString_uses_locale_words() async throws {
        let store = AppLanguageStore.shared
        store.setLanguage(.korean)
        defer { store.setLanguage(.system) }

        let s = LocaleAwareFormatter.shared.relativeString(
            for: Date().addingTimeInterval(-3600),
            relativeTo: Date(),
            style: .full
        )
        // Korean "1 hour ago" 형식: should contain non-ASCII (Korean hangul)
        let hasNonAscii = s.unicodeScalars.contains { $0.value > 0x7F }
        #expect(hasNonAscii, "expected Korean wording, got: \(s)")
    }

    @Test func test_concurrent_calls_do_not_crash() async throws {
        // Stress the lock — DateFormatter is non-thread-safe but our API
        // formats inside the lock, so concurrent calls must be safe.
        let store = AppLanguageStore.shared
        store.setLanguage(.english)
        defer { store.setLanguage(.system) }

        await withTaskGroup(of: String.self) { group in
            for i in 0..<50 {
                group.addTask {
                    let date = Date(timeIntervalSince1970: TimeInterval(i * 86_400))
                    return LocaleAwareFormatter.shared.string(from: date, format: "yyyy-MM-dd")
                }
            }
            var seen = 0
            for await _ in group { seen += 1 }
            #expect(seen == 50)
        }
    }

    @Test func test_mondayFirstWeekdaySymbols_count_and_locale() async throws {
        let store = AppLanguageStore.shared
        defer { store.setLanguage(.system) }

        store.setLanguage(.english)
        let en = LocaleAwareFormatter.shared.mondayFirstWeekdaySymbols(short: true)
        #expect(en.count == 7)
        // veryShort English: Sun..Sat = S,M,T,W,T,F,S → Monday-first = M,T,W,T,F,S,S
        #expect(en == ["M", "T", "W", "T", "F", "S", "S"])

        store.setLanguage(.japanese)
        let ja = LocaleAwareFormatter.shared.mondayFirstWeekdaySymbols(short: true)
        #expect(ja.count == 7)
        // Japanese veryShort weekday symbols are 月火水木金土日; Monday-first:
        #expect(ja == ["月", "火", "水", "木", "金", "土", "日"])
    }

    @Test func test_dateStyle_returns_locale_bound_copy() async throws {
        let store = AppLanguageStore.shared
        store.setLanguage(.japanese)
        defer { store.setLanguage(.system) }

        let style = LocaleAwareFormatter.shared.dateStyle(Date.FormatStyle().day().month())
        let sample = style.format(Date(timeIntervalSince1970: 0))
        #expect(sample.contains("月"))
    }
}
