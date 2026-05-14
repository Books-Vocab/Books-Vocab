import Foundation
import Testing
@testable import BooksBrowser

/// Pins the error-classification & retry-policy contract that every authenticated KG call
/// (vocab CRUD, sync, graph fetch, podcast metadata) relies on. These are pure-function
/// predicates with no Network/URLSession dependency — perfect for fast unit pinning.
struct KGServiceErrorTests {

    // MARK: - KGError.isNetworkRelated

    @Test func offline_is_network_related() {
        #expect(KGError.offline.isNetworkRelated)
    }

    @Test func networkError_is_network_related() {
        let urlErr = URLError(.timedOut)
        #expect(KGError.networkError(underlying: urlErr).isNetworkRelated)
    }

    @Test func unauthorized_is_not_network_related() {
        // Auth failures should not be classified as network — UI surfaces a login prompt,
        // not an "offline" banner.
        #expect(!KGError.unauthorized.isNetworkRelated)
        #expect(!KGError.notAuthenticated.isNetworkRelated)
    }

    @Test func httpError_is_not_network_related() {
        #expect(!KGError.httpError(statusCode: 500, detail: "boom").isNetworkRelated)
        #expect(!KGError.httpError(statusCode: 404, detail: "missing").isNetworkRelated)
    }

    @Test func serverError_is_not_network_related() {
        #expect(!KGError.serverError("invalid response").isNetworkRelated)
    }

    @Test func decodingError_is_not_network_related() {
        struct DummyDecodingErr: Error {}
        #expect(!KGError.decodingError(underlying: DummyDecodingErr()).isNetworkRelated)
    }

    // MARK: - KGError.isRetryable

    @Test func offline_is_retryable() {
        #expect(KGError.offline.isRetryable)
    }

    @Test func networkError_is_retryable() {
        #expect(KGError.networkError(underlying: URLError(.networkConnectionLost)).isRetryable)
    }

    @Test func http_5xx_is_retryable() {
        #expect(KGError.httpError(statusCode: 500, detail: "").isRetryable)
        #expect(KGError.httpError(statusCode: 502, detail: "").isRetryable)
        #expect(KGError.httpError(statusCode: 503, detail: "").isRetryable)
        #expect(KGError.httpError(statusCode: 599, detail: "").isRetryable)
    }

    @Test func http_429_is_retryable() {
        // Rate-limit must be retryable so the policy honours Retry-After backoff.
        #expect(KGError.httpError(statusCode: 429, detail: "").isRetryable)
    }

    @Test func http_4xx_other_than_429_not_retryable() {
        // 400/401/403/404 are client-side terminal — retrying just wastes quota.
        #expect(!KGError.httpError(statusCode: 400, detail: "").isRetryable)
        #expect(!KGError.httpError(statusCode: 401, detail: "").isRetryable)
        #expect(!KGError.httpError(statusCode: 403, detail: "").isRetryable)
        #expect(!KGError.httpError(statusCode: 404, detail: "").isRetryable)
    }

    @Test func http_2xx_not_retryable() {
        // Defensive: success codes wrapped in httpError (shouldn't happen, but guard anyway).
        #expect(!KGError.httpError(statusCode: 200, detail: "").isRetryable)
        #expect(!KGError.httpError(statusCode: 201, detail: "").isRetryable)
    }

    @Test func unauthorized_not_retryable() {
        #expect(!KGError.unauthorized.isRetryable)
        #expect(!KGError.notAuthenticated.isRetryable)
    }

    @Test func serverError_not_retryable() {
        #expect(!KGError.serverError("invalid url").isRetryable)
    }

    @Test func decodingError_not_retryable() {
        struct E: Error {}
        // Decode failures indicate a schema mismatch — retrying won't fix it.
        #expect(!KGError.decodingError(underlying: E()).isRetryable)
    }

    // MARK: - KGError.errorDescription is non-empty for every case

    @Test func error_description_present_for_all_cases() {
        let cases: [KGError] = [
            .notAuthenticated,
            .unauthorized,
            .offline,
            .httpError(statusCode: 500, detail: "x"),
            .decodingError(underlying: URLError(.cannotDecodeRawData)),
            .networkError(underlying: URLError(.timedOut)),
            .serverError("bad")
        ]
        for err in cases {
            #expect(err.errorDescription != nil && !(err.errorDescription ?? "").isEmpty,
                    "KGError.\(err) must surface a user-visible description")
        }
    }

    // MARK: - RetryPolicy presets

    @Test func retry_policy_none_disables_retries() {
        let p = RetryPolicy.none
        #expect(p.maxAttempts == 1)
        #expect(p.baseDelay == 0)
        #expect(p.retryableStatusCodes.isEmpty)
    }

    @Test func retry_policy_default_three_attempts_one_second_base() {
        let p = RetryPolicy.default
        #expect(p.maxAttempts == 3)
        #expect(p.baseDelay == 1.0)
        #expect(p.retryableStatusCodes == [429, 500, 502, 503])
    }

    @Test func retry_policy_aggressive_five_attempts_half_second_base() {
        let p = RetryPolicy.aggressive
        #expect(p.maxAttempts == 5)
        #expect(p.baseDelay == 0.5)
        #expect(p.retryableStatusCodes == [429, 500, 502, 503])
    }

    @Test func retry_policy_default_does_not_retry_504() {
        // Documenting a known gap: 504 Gateway Timeout is NOT in the default retry set.
        // If product decides to add it later, this test must be flipped intentionally.
        #expect(!RetryPolicy.default.retryableStatusCodes.contains(504))
    }

    @Test func retry_policy_default_does_not_retry_401() {
        // 401 must never auto-retry — it goes through dedicated token-refresh path.
        #expect(!RetryPolicy.default.retryableStatusCodes.contains(401))
        #expect(!RetryPolicy.aggressive.retryableStatusCodes.contains(401))
    }

    // MARK: - SyncKeys payload version contract

    @Test func sync_payload_version_is_positive_int() {
        // If product bumps the schema, this test will break and force a deliberate review.
        #expect(KGService.SyncKeys.currentPayloadVersion == 1)
        #expect(KGService.SyncKeys.incrementalBoundary == "kg_last_incremental_sync")
        #expect(KGService.SyncKeys.payloadVersion == "kg_review_payload_version")
    }
}
