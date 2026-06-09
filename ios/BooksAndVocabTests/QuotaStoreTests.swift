import Foundation
import Testing
@testable import BooksAndVocab

/// Pins the QuotaStore contract that gates UI surfaces (quota banner, exhausted lockout)
/// and the HTTP header → store update path that runs on every authenticated KG response.
///
/// Each test instantiates a fresh `QuotaStore` (not `.shared`) so they never leak the
/// process-wide singleton's state across the suite.
struct QuotaStoreTests {

    // MARK: - Level boundary matrix

    @Test func level_normal_for_fraction_one() {
        let store = QuotaStore()
        store.update(fraction: 1.0, resetSeconds: 0)
        #expect(store.level == .normal)
        #expect(!store.isExhausted)
    }

    @Test func level_normal_for_fraction_at_warning_upper_open_bound() {
        // 0.3 is the open upper bound of `warning` — exactly 0.3 must fall into `normal`.
        let store = QuotaStore()
        store.update(fraction: 0.3, resetSeconds: 0)
        #expect(store.level == .normal)
    }

    @Test func level_warning_just_below_thirty_percent() {
        let store = QuotaStore()
        store.update(fraction: 0.2999, resetSeconds: 0)
        #expect(store.level == .warning)
    }

    @Test func level_warning_at_ten_percent_lower_bound() {
        // `warning` is 0.1..<0.3 — exactly 0.1 must be `warning`, not `critical`.
        let store = QuotaStore()
        store.update(fraction: 0.1, resetSeconds: 0)
        #expect(store.level == .warning)
    }

    @Test func level_critical_just_below_ten_percent() {
        let store = QuotaStore()
        store.update(fraction: 0.0999, resetSeconds: 0)
        #expect(store.level == .critical)
    }

    @Test func level_critical_just_above_zero() {
        // 0 is the open lower bound of `critical` — any value > 0 is `critical`.
        let store = QuotaStore()
        store.update(fraction: 0.0001, resetSeconds: 0)
        #expect(store.level == .critical)
        #expect(!store.isExhausted)
    }

    @Test func level_exhausted_at_exact_zero() {
        let store = QuotaStore()
        store.update(fraction: 0, resetSeconds: 0)
        #expect(store.level == .exhausted)
        #expect(store.isExhausted)
    }

    @Test func level_exhausted_for_negative_fraction() {
        // Backend bug or clock skew could send negative — UI must still treat as exhausted, not normal.
        let store = QuotaStore()
        store.update(fraction: -0.1, resetSeconds: 0)
        #expect(store.level == .exhausted)
        #expect(store.isExhausted)
    }

    // MARK: - HTTP header parsing

    private func makeResponse(headers: [String: String]) -> HTTPURLResponse {
        HTTPURLResponse(
            url: URL(string: "\(TestBrandIdentity.publicBaseURL)/api/health")!,
            statusCode: 200,
            httpVersion: nil,
            headerFields: headers
        )!
    }

    @Test func update_from_response_parses_both_headers() {
        let store = QuotaStore()
        let resp = makeResponse(headers: [
            "X-Quota-Fraction": "0.42",
            "X-Quota-Reset": "1800"
        ])
        store.update(from: resp)
        #expect(store.fraction == 0.42)
        #expect(store.resetSeconds == 1800)
    }

    @Test func update_from_response_keeps_prior_value_when_header_absent() {
        let store = QuotaStore()
        store.update(fraction: 0.5, resetSeconds: 600)
        // No X-Quota-* headers — store must hold prior state, not reset to 0.
        store.update(from: makeResponse(headers: ["Content-Type": "application/json"]))
        #expect(store.fraction == 0.5)
        #expect(store.resetSeconds == 600)
    }

    @Test func update_from_response_ignores_unparseable_header() {
        let store = QuotaStore()
        store.update(fraction: 0.7, resetSeconds: 120)
        store.update(from: makeResponse(headers: [
            "X-Quota-Fraction": "not-a-number",
            "X-Quota-Reset": "also-junk"
        ]))
        #expect(store.fraction == 0.7)
        #expect(store.resetSeconds == 120)
    }

    @Test func update_from_response_partial_header_updates_only_present_field() {
        let store = QuotaStore()
        store.update(fraction: 0.9, resetSeconds: 300)
        store.update(from: makeResponse(headers: ["X-Quota-Reset": "60"]))
        // Fraction untouched, reset overwritten.
        #expect(store.fraction == 0.9)
        #expect(store.resetSeconds == 60)
    }

    // MARK: - resetText formatting

    @Test func reset_text_renders_minutes_only_when_under_an_hour() {
        let store = QuotaStore()
        store.update(fraction: 0.5, resetSeconds: 600) // 10 minutes
        // L10n.format may substitute literal placeholders if no .strings entry exists; we
        // assert on the digits and `m` marker that the format produces in either case.
        #expect(store.resetText.contains("10"))
        #expect(store.resetText.contains("m"))
        #expect(!store.resetText.contains("h"))
    }

    @Test func reset_text_renders_hours_and_minutes_when_over_an_hour() {
        let store = QuotaStore()
        store.update(fraction: 0.5, resetSeconds: 3 * 3600 + 25 * 60) // 3h 25m
        #expect(store.resetText.contains("3"))
        #expect(store.resetText.contains("25"))
        #expect(store.resetText.contains("h"))
        #expect(store.resetText.contains("m"))
    }

    @Test func reset_text_zero_seconds_renders_zero_minutes() {
        let store = QuotaStore()
        store.update(fraction: 1.0, resetSeconds: 0)
        // Boundary: 0 seconds is "0m 後重置" — must not produce an h block.
        #expect(store.resetText.contains("0"))
        #expect(!store.resetText.contains("h"))
    }

    // MARK: - reset (account-switch / logout isolation)

    @Test func reset_restores_initial_state() {
        // Account A leaves quota state behind; logout/account-switch must wipe it so
        // account B never sees A's remaining quota before the next response header lands.
        let store = QuotaStore()
        store.update(fraction: 0.3, resetSeconds: 1800)
        store.reset()
        #expect(store.fraction == 1.0)
        #expect(store.resetSeconds == 0)
        #expect(store.level == .normal)
        #expect(!store.isExhausted)
    }

    @Test func reset_from_exhausted_returns_to_normal() {
        // The lockout case: an exhausted A account must not lock out a fresh B account.
        let store = QuotaStore()
        store.update(fraction: 0, resetSeconds: 600)
        store.reset()
        #expect(store.level == .normal)
        #expect(!store.isExhausted)
    }

    // MARK: - Sequential updates

    @Test func update_overwrites_prior_state() {
        let store = QuotaStore()
        store.update(fraction: 0.8, resetSeconds: 600)
        store.update(fraction: 0.05, resetSeconds: 60)
        #expect(store.fraction == 0.05)
        #expect(store.resetSeconds == 60)
        #expect(store.level == .critical)
    }
}
