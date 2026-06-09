import Foundation
import Testing
@testable import BooksAndVocab

/// Pins the *pure logic* seams of the `SubscriptionManager` family — the billing core
/// (`SubscriptionManager` + `+Purchase`/`+Refresh`/`+StoreKit`/`+Helpers`).
///
/// Honesty note — what is NOT covered, and why:
///
/// - StoreKit-bound paths (`loadProducts`, `purchasePro`, `restorePurchases`,
///   `syncTransaction`, `syncCurrentEntitlements`, `queryWillAutoRenew`,
///   `appStoreEnvironment(for:)`, `checkVerified(_:)`, `optimisticEntitlements(from:)`)
///   require `Product`, `Transaction`, `VerificationResult` — StoreKit types that
///   cannot be constructed in a unit-test process without a StoreKit testing session
///   and a real App Store / StoreKit configuration. There is no injection seam for
///   them, so they are deliberately left out rather than faked with tautologies.
///
/// - `refresh(...)` / `resyncAfterManagement(...)` interleave a `KGServing` network
///   call with StoreKit `queryWillAutoRenew()`. The network half has a protocol seam
///   (`KGServing`) but the StoreKit half does not, so the full method cannot be
///   exercised deterministically. The *pure model logic* it depends on
///   (`KGSubscriptionStatus.isExpired` / `.isCancelledButActive` / `.parseExpiryDate`)
///   is what gates its branches — and that is fully covered below.
///
/// What IS covered: the deterministic, dependency-free seams —
/// `stableUUID(for:)`, `purchaseOptions(for:)`, `merge(...)`, `inferredStatus(for:)`,
/// and the `KGSubscriptionStatus` expiry/cancellation predicates that drive
/// local downgrade and expiry-timer scheduling.
struct SubscriptionManagerTests {

    // MARK: - Fixtures

    /// A baseline subscription status; individual fields are overridden per test.
    private func status(
        isActive: Bool = false,
        productId: String? = nil,
        priceDisplay: String? = nil,
        status: String = "inactive",
        isTrial: Bool = false,
        willRenew: Bool = false,
        expiresAt: String? = nil,
        source: String = "app_store"
    ) -> KGSubscriptionStatus {
        KGSubscriptionStatus(
            is_active: isActive,
            product_id: productId,
            plan_name: "Books & Vocab Pro",
            price_display: priceDisplay,
            status: status,
            is_trial: isTrial,
            trial_days: 7,
            will_renew: willRenew,
            expires_at: expiresAt,
            source: source,
            last_synced_at: nil
        )
    }

    // MARK: - stableUUID: deterministic SHA256 → UUID derivation

    @MainActor
    @Test func stableUUID_is_deterministic_for_same_userId() {
        let mgr = SubscriptionManager.shared
        let a = mgr.stableUUID(for: "user-abc-123")
        let b = mgr.stableUUID(for: "user-abc-123")
        #expect(a != nil)
        #expect(a == b)
    }

    @MainActor
    @Test func stableUUID_differs_across_distinct_userIds() {
        let mgr = SubscriptionManager.shared
        let a = mgr.stableUUID(for: "user-one")
        let b = mgr.stableUUID(for: "user-two")
        #expect(a != nil)
        #expect(b != nil)
        #expect(a != b)
    }

    @MainActor
    @Test func stableUUID_handles_empty_and_unicode_userId() {
        // SHA256 always yields 32 bytes → prefix(16) always succeeds; never nil.
        let mgr = SubscriptionManager.shared
        #expect(mgr.stableUUID(for: "") != nil)
        #expect(mgr.stableUUID(for: "用戶-表情-🔑") != nil)
        // Determinism holds for unicode too.
        #expect(mgr.stableUUID(for: "用戶-表情-🔑") == mgr.stableUUID(for: "用戶-表情-🔑"))
    }

    @MainActor
    @Test func stableUUID_matches_known_sha256_prefix() {
        // Pin the exact derivation: SHA256("kg") prefix(16), uppercased, UUID-formatted.
        // SHA256("kg") = 131ed734290d30f32aedb3548cc92b42... — first 16 bytes form this UUID.
        let mgr = SubscriptionManager.shared
        let uuid = mgr.stableUUID(for: "kg")
        #expect(uuid != nil)
        // The first 16 hex-pairs of SHA256("kg"):
        // 13 1e d7 34 29 0d 30 f3 2a ed b3 54 8c c9 2b 42
        #expect(uuid?.uuidString == "131ED734-290D-30F3-2AED-B3548CC92B42")
    }

    // MARK: - purchaseOptions: appAccountToken gating

    @MainActor
    @Test func purchaseOptions_empty_when_userId_nil() {
        // No logged-in user → no appAccountToken attached to the purchase.
        let mgr = SubscriptionManager.shared
        #expect(mgr.purchaseOptions(for: nil).isEmpty)
    }

    @MainActor
    @Test func purchaseOptions_carries_single_option_for_valid_userId() {
        // A non-nil userId yields exactly one option (the appAccountToken).
        // The token value itself is StoreKit-opaque and not inspectable here.
        let mgr = SubscriptionManager.shared
        #expect(mgr.purchaseOptions(for: "user-xyz").count == 1)
    }

    @MainActor
    @Test func purchaseOptions_handles_empty_string_userId() {
        // Empty string is still a non-nil userId → stableUUID succeeds → one option.
        let mgr = SubscriptionManager.shared
        #expect(mgr.purchaseOptions(for: "").count == 1)
    }

    // MARK: - merge: pure field-level overlay onto KGSubscriptionStatus

    @MainActor
    @Test func merge_with_no_overrides_is_identity() {
        let mgr = SubscriptionManager.shared
        let base = status(isActive: true, status: "active", willRenew: true)
        #expect(mgr.merge(base) == base)
    }

    @MainActor
    @Test func merge_overrides_only_specified_fields() {
        let mgr = SubscriptionManager.shared
        let base = status(
            isActive: false,
            productId: "old.id",
            priceDisplay: "NT$30",
            status: "inactive",
            isTrial: false,
            willRenew: false
        )
        let merged = mgr.merge(
            base,
            productId: "new.id",
            priceDisplay: "NT$90",
            status: "active",
            isActive: true,
            isTrial: true,
            willRenew: true
        )
        #expect(merged.product_id == "new.id")
        #expect(merged.price_display == "NT$90")
        #expect(merged.status == "active")
        #expect(merged.is_active == true)
        #expect(merged.is_trial == true)
        #expect(merged.will_renew == true)
        // Untouched fields are preserved verbatim.
        #expect(merged.plan_name == base.plan_name)
        #expect(merged.trial_days == base.trial_days)
        #expect(merged.expires_at == base.expires_at)
        #expect(merged.source == base.source)
        #expect(merged.last_synced_at == base.last_synced_at)
    }

    @MainActor
    @Test func merge_partial_override_keeps_rest_intact() {
        // Only `willRenew` flips — every other field must survive untouched.
        // This is the exact shape of the refresh.swift will_renew reconciliation.
        let mgr = SubscriptionManager.shared
        let base = status(isActive: true, productId: "p.id", status: "active", willRenew: true)
        let merged = mgr.merge(base, willRenew: false)
        #expect(merged.will_renew == false)
        #expect(merged.is_active == base.is_active)
        #expect(merged.product_id == base.product_id)
        #expect(merged.status == base.status)
    }

    @MainActor
    @Test func merge_can_express_local_expired_downgrade() {
        // The +Refresh.swift local-downgrade path: status→"expired", isActive→false.
        let mgr = SubscriptionManager.shared
        let base = status(isActive: true, status: "active", willRenew: false)
        let downgraded = mgr.merge(base, status: "expired", isActive: false)
        #expect(downgraded.is_active == false)
        #expect(downgraded.status == "expired")
        #expect(downgraded.will_renew == false) // unchanged
    }

    // MARK: - inferredStatus: trial-aware status string for sync snapshots

    @MainActor
    @Test func inferredStatus_falls_back_to_active_when_product_nil_and_not_trial() {
        // With a nil product and a non-trial entitlement the method returns "active".
        // Asserted against the shared singleton's default (non-trial) entitlements.
        let mgr = SubscriptionManager.shared
        // Sanity-pin the precondition this assertion depends on.
        #expect(mgr.entitlements.pro.is_trial == false)
        #expect(mgr.inferredStatus(for: nil) == "active")
    }

    // MARK: - KGSubscriptionStatus.parseExpiryDate (drives refresh + expiry timer)

    @Test func parseExpiryDate_accepts_fractional_seconds_iso8601() {
        let date = KGSubscriptionStatus.parseExpiryDate("2026-01-15T08:30:00.000Z")
        #expect(date != nil)
    }

    @Test func parseExpiryDate_accepts_plain_iso8601_without_fraction() {
        // The fallback formatter must catch non-fractional ISO-8601.
        let date = KGSubscriptionStatus.parseExpiryDate("2026-01-15T08:30:00Z")
        #expect(date != nil)
    }

    @Test func parseExpiryDate_rejects_garbage_and_empty() {
        #expect(KGSubscriptionStatus.parseExpiryDate("not-a-date") == nil)
        #expect(KGSubscriptionStatus.parseExpiryDate("") == nil)
        #expect(KGSubscriptionStatus.parseExpiryDate("2026/01/15") == nil)
    }

    // MARK: - KGSubscriptionStatus.isExpired (gates local downgrade in +Refresh)

    @Test func isExpired_true_for_past_expiry() {
        let past = ISO8601DateFormatter().string(from: Date(timeIntervalSinceNow: -3600))
        #expect(status(expiresAt: past).isExpired == true)
    }

    @Test func isExpired_false_for_future_expiry() {
        let future = ISO8601DateFormatter().string(from: Date(timeIntervalSinceNow: 3600))
        #expect(status(expiresAt: future).isExpired == false)
    }

    @Test func isExpired_false_when_expiry_missing_or_empty() {
        // No expiry date → cannot prove expiry → must not downgrade.
        #expect(status(expiresAt: nil).isExpired == false)
        #expect(status(expiresAt: "").isExpired == false)
    }

    @Test func isExpired_false_when_expiry_unparseable() {
        // Garbage expiry string is treated as "unknown", never as expired.
        #expect(status(expiresAt: "garbage").isExpired == false)
    }

    // MARK: - KGSubscriptionStatus.isCancelledButActive (gates expiry-timer scheduling)

    @Test func isCancelledButActive_true_when_active_and_not_renewing() {
        // Active + will-not-renew + non-admin source → scheduled for expiry refresh.
        let s = status(isActive: true, willRenew: false, source: "app_store")
        #expect(s.isCancelledButActive == true)
    }

    @Test func isCancelledButActive_false_when_renewing() {
        let s = status(isActive: true, willRenew: true, source: "app_store")
        #expect(s.isCancelledButActive == false)
    }

    @Test func isCancelledButActive_false_when_inactive() {
        let s = status(isActive: false, willRenew: false, source: "app_store")
        #expect(s.isCancelledButActive == false)
    }

    @Test func isCancelledButActive_false_for_admin_grant() {
        // Admin-granted Pro never auto-renews but must NOT be treated as cancelled —
        // it has no App Store expiry to schedule against.
        let s = status(isActive: true, willRenew: false, source: "admin")
        #expect(s.isCancelledButActive == false)
    }

    // MARK: - KGSubscriptionStatus.formattedExpiry (display path)

    @Test func formattedExpiry_returns_placeholder_for_nil_and_empty() {
        let placeholder = L10n.string("未知時間")
        #expect(KGSubscriptionStatus.formattedExpiry(nil) == placeholder)
        #expect(KGSubscriptionStatus.formattedExpiry("") == placeholder)
    }

    @Test func formattedExpiry_passes_through_unparseable_string() {
        // An unrecognised string is echoed back rather than replaced — surfacing the
        // raw backend value instead of hiding it behind a placeholder.
        #expect(KGSubscriptionStatus.formattedExpiry("weird-value") == "weird-value")
    }

    @Test func formattedExpiry_renders_valid_iso8601_into_display_format() {
        // A valid ISO-8601 string must be reformatted (no longer equal to the input,
        // and no longer the placeholder).
        let rendered = KGSubscriptionStatus.formattedExpiry("2026-01-15T08:30:00.000Z")
        #expect(rendered != "2026-01-15T08:30:00.000Z")
        #expect(rendered != L10n.string("未知時間"))
        #expect(!rendered.isEmpty)
    }

    // MARK: - SubscriptionManager.defaultEntitlements (logged-out reset state)

    @MainActor
    @Test func defaultEntitlements_is_inactive_non_pro() {
        // `refresh` resets to this when the user is logged out — must grant no access.
        let def = SubscriptionManager.defaultEntitlements
        #expect(def.pro.is_active == false)
        #expect(def.pro.status == "inactive")
        #expect(def.pro.is_trial == false)
        #expect(def.pro.will_renew == false)
        #expect(def.pro.product_id == nil)
        #expect(def.pro.source == "app_store")
        // isExpired on the default must be false (no expiry date present).
        #expect(def.pro.isExpired == false)
        // And it must not look "cancelled but active".
        #expect(def.pro.isCancelledButActive == false)
    }

    // MARK: - Static configuration constants

    @MainActor
    @Test func proProductID_is_stable_and_exposed_via_instance() {
        // The product identifier is a release-critical constant; pin it and confirm
        // the instance accessor mirrors the type-level constant.
        #expect(SubscriptionManager.proProductID == "com.wordnexus.pro.monthly")
        #expect(SubscriptionManager.shared.proProductIdentifier == SubscriptionManager.proProductID)
    }
}
