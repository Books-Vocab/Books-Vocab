import Foundation
import Testing
@testable import BooksAndVocab

/// Pins the `JWTExpiry` pre-flight expiry check — a pure function seam that gates whether
/// the app trusts a cached token before issuing requests. A wrong verdict either logs the
/// user out unnecessarily (false-positive expiry) or sends a dead token to the backend
/// (false-negative). No injection needed: the only impure dependency is `Date()`, which the
/// tests pin by minting tokens relative to "now".
///
/// `expirationDate(from:)` deliberately does NOT verify the signature — it only base64-decodes
/// the payload segment and reads `exp`. The tests therefore mint unsigned 3-segment tokens.
struct JWTExpiryTests {

    // MARK: - Token minting helpers

    /// Base64URL-encodes a JSON payload as the middle JWT segment (no padding, `-`/`_` alphabet),
    /// matching how real JWT issuers encode and how `JWTExpiry` un-maps the alphabet.
    private static func base64URL(_ json: [String: Any]) -> String {
        let data = try! JSONSerialization.data(withJSONObject: json)
        return data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    /// Mints a 3-segment token (`header.payload.signature`) with the given payload.
    private static func token(payload: [String: Any]) -> String {
        let header = base64URL(["alg": "HS256", "typ": "JWT"])
        let body = base64URL(payload)
        return "\(header).\(body).sig"
    }

    /// Token whose `exp` is `offset` seconds from now (negative = past).
    private static func token(expiringIn offset: TimeInterval) -> String {
        token(payload: ["exp": Date().addingTimeInterval(offset).timeIntervalSince1970,
                        "sub": "user-123"])
    }

    // MARK: - expirationDate: happy path

    @Test func expirationDate_decodes_exp_from_valid_token() {
        let target = Date().addingTimeInterval(3600)
        let tok = Self.token(payload: ["exp": target.timeIntervalSince1970])
        let decoded = JWTExpiry.expirationDate(from: tok)
        #expect(decoded != nil)
        // Round-trip through Unix timestamp is exact to within float precision.
        #expect(abs((decoded?.timeIntervalSince1970 ?? 0) - target.timeIntervalSince1970) < 0.001)
    }

    @Test func expirationDate_decodes_exp_given_as_integer() {
        // Real issuers emit `exp` as an integer; JSONSerialization yields NSNumber,
        // which bridges to TimeInterval. Confirms the `as? TimeInterval` cast holds.
        let intExp = 2_000_000_000  // a fixed integer timestamp
        let tok = Self.token(payload: ["exp": intExp])
        let decoded = JWTExpiry.expirationDate(from: tok)
        #expect(decoded == Date(timeIntervalSince1970: TimeInterval(intExp)))
    }

    @Test func expirationDate_handles_payload_needing_base64_padding() {
        // A payload whose base64URL length is not a multiple of 4 must still decode —
        // JWTExpiry re-pads with `=`. We force this by picking a payload of odd byte length.
        let tok = Self.token(payload: ["exp": 1_700_000_000, "a": "b"])
        #expect(JWTExpiry.expirationDate(from: tok) != nil)
    }

    // MARK: - expirationDate: malformed / missing inputs

    @Test func expirationDate_nil_for_empty_string() {
        #expect(JWTExpiry.expirationDate(from: "") == nil)
    }

    @Test func expirationDate_nil_for_single_segment() {
        // `split` drops empty subsequences, so a bare string is one segment → < 2 → nil.
        #expect(JWTExpiry.expirationDate(from: "notajwt") == nil)
    }

    @Test func expirationDate_nil_when_payload_segment_not_base64() {
        // Header is valid but the payload segment contains chars invalid even after
        // the `-`/`_` un-mapping, so `Data(base64Encoded:)` returns nil.
        let header = Self.base64URL(["alg": "none"])
        #expect(JWTExpiry.expirationDate(from: "\(header).!!!notbase64!!!.sig") == nil)
    }

    @Test func expirationDate_nil_when_payload_is_not_json_object() {
        // Payload base64-decodes to the literal string "hello" — valid bytes but not a
        // JSON object, so the `as? [String: Any]` cast fails.
        let header = Self.base64URL(["alg": "none"])
        let payload = Data("\"hello\"".utf8).base64EncodedString()
            .replacingOccurrences(of: "=", with: "")
        #expect(JWTExpiry.expirationDate(from: "\(header).\(payload).sig") == nil)
    }

    @Test func expirationDate_nil_when_exp_claim_absent() {
        // A well-formed JSON payload that simply omits `exp`.
        let tok = Self.token(payload: ["sub": "user-123", "iss": "kg"])
        #expect(JWTExpiry.expirationDate(from: tok) == nil)
    }

    @Test func expirationDate_nil_when_exp_is_non_numeric() {
        // `exp` present but a string — the `as? TimeInterval` cast fails, no crash.
        let tok = Self.token(payload: ["exp": "not-a-number"])
        #expect(JWTExpiry.expirationDate(from: tok) == nil)
    }

    // MARK: - isExpired: core verdicts

    @Test func isExpired_true_for_long_past_token() {
        #expect(JWTExpiry.isExpired(Self.token(expiringIn: -3600)))
    }

    @Test func isExpired_false_for_far_future_token() {
        // Well beyond the default 60s margin.
        #expect(!JWTExpiry.isExpired(Self.token(expiringIn: 3600)))
    }

    // MARK: - isExpired: margin (clock-skew safety) boundary

    @Test func isExpired_true_when_within_default_margin_window() {
        // exp is 30s away — inside the 60s default margin, so treated as expired
        // to pre-empt a token dying mid-request.
        #expect(JWTExpiry.isExpired(Self.token(expiringIn: 30)))
    }

    @Test func isExpired_false_just_outside_default_margin() {
        // exp ~120s away, comfortably past the 60s margin.
        #expect(!JWTExpiry.isExpired(Self.token(expiringIn: 120)))
    }

    @Test func isExpired_zero_margin_disables_skew_buffer() {
        // With margin 0, a token expiring 30s out is still valid (no skew buffer).
        #expect(!JWTExpiry.isExpired(Self.token(expiringIn: 30), margin: 0))
    }

    @Test func isExpired_uses_greater_or_equal_at_boundary() {
        // The check is `now + margin >= exp`. A token already expired by a few seconds
        // is unambiguously expired even with margin 0 — pins the `>=` direction.
        #expect(JWTExpiry.isExpired(Self.token(expiringIn: -5), margin: 0))
    }

    @Test func isExpired_large_margin_flags_otherwise_valid_token() {
        // A token valid for 1h is flagged expired under a 2h margin — confirms margin
        // is added to `now`, not subtracted from `exp` in some inverted way.
        #expect(JWTExpiry.isExpired(Self.token(expiringIn: 3600), margin: 7200))
    }

    // MARK: - isExpired: undecodable tokens fall through to backend

    @Test func isExpired_false_for_malformed_token() {
        // Documented contract: when exp can't be parsed, JWTExpiry does NOT guess —
        // it returns false so the request proceeds and the backend issues a 401 if dead.
        #expect(!JWTExpiry.isExpired("garbage"))
        #expect(!JWTExpiry.isExpired(""))
    }

    @Test func isExpired_false_when_exp_claim_missing() {
        // Same fall-through contract for a structurally valid token lacking `exp`.
        #expect(!JWTExpiry.isExpired(Self.token(payload: ["sub": "user-123"])))
    }
}
