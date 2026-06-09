#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

/// Pins `SubscriptionPaywallCopy` — the pure paywall copy resolver behind
/// SubscriptionPaywallSheet. These strings are App Store 3.1.2(c) pricing-
/// disclosure sensitive, so the branch logic (admin grant vs App Store vs
/// remote price vs loading; trial inclusion; CTA price embedding) is locked
/// here rather than left in untestable View computed properties.
struct SubscriptionPaywallCopyTests {

    /// Builds a `KGSubscriptionStatus` with paywall-relevant fields; the rest
    /// default to inert values.
    private func status(
        isActive: Bool = false,
        source: String = "appstore",
        trialDays: Int? = nil,
        expiresAt: String? = nil,
        priceDisplay: String? = nil
    ) -> KGSubscriptionStatus {
        KGSubscriptionStatus(
            is_active: isActive,
            product_id: nil,
            plan_name: nil,
            price_display: priceDisplay,
            status: isActive ? "active" : "free",
            is_trial: false,
            trial_days: trialDays,
            will_renew: true,
            expires_at: expiresAt,
            source: source,
            last_synced_at: nil
        )
    }

    // MARK: - Admin gate

    @Test func isAdminGranted_requiresActiveAndAdminSource() {
        #expect(SubscriptionPaywallCopy.isAdminGranted(status(isActive: true, source: "admin")))
        #expect(!SubscriptionPaywallCopy.isAdminGranted(status(isActive: false, source: "admin")))
        #expect(!SubscriptionPaywallCopy.isAdminGranted(status(isActive: true, source: "appstore")))
    }

    /// entitlementSource keys on `source == "admin"` ALONE (no is_active check) —
    /// distinct from isAdminGranted. Pin so the two don't get conflated.
    @Test func entitlementSource_keysOnSourceOnly() {
        let adminActive = SubscriptionPaywallCopy.entitlementSource(status(isActive: true, source: "admin"))
        let adminInactive = SubscriptionPaywallCopy.entitlementSource(status(isActive: false, source: "admin"))
        let appstore = SubscriptionPaywallCopy.entitlementSource(status(source: "appstore"))
        #expect(adminActive == adminInactive)   // both → 管理員授權
        #expect(adminActive != appstore)
    }

    // MARK: - Trial days

    @Test func trialDays_fallsBackToDefault() {
        #expect(SubscriptionPaywallCopy.trialDays(status(trialDays: nil)) == SubscriptionPaywallCopy.defaultTrialDays)
        #expect(SubscriptionPaywallCopy.trialDays(status(trialDays: 14)) == 14)
    }

    @Test func trialInfo_nilForAdminOrZeroDays() {
        #expect(SubscriptionPaywallCopy.trialInfo(status(isActive: true, source: "admin")) == nil)
        #expect(SubscriptionPaywallCopy.trialInfo(status(trialDays: 0)) == nil)
        #expect(SubscriptionPaywallCopy.trialInfo(status(trialDays: 7))?.contains("7") == true)
    }

    // MARK: - Billed amount precedence

    @Test func billedAmount_adminWithExpiry() {
        let s = status(isActive: true, source: "admin", expiresAt: "2026-12-31")
        let line = SubscriptionPaywallCopy.billedAmount(s, productDisplayPrice: "$4.99")
        #expect(line.contains("2026-12-31"))
        #expect(!line.contains("$4.99"))   // admin branch wins over product price
    }

    @Test func billedAmount_productPriceWinsOverRemote() {
        let s = status(priceDisplay: "NT$170")
        let line = SubscriptionPaywallCopy.billedAmount(s, productDisplayPrice: "$4.99")
        #expect(line.contains("$4.99"))
        #expect(!line.contains("NT$170"))
    }

    @Test func billedAmount_remotePriceWhenNoProduct() {
        let s = status(priceDisplay: "NT$170")
        #expect(SubscriptionPaywallCopy.billedAmount(s, productDisplayPrice: nil) == "NT$170")
    }

    @Test func billedAmount_loadingWhenNothing() {
        let a = SubscriptionPaywallCopy.billedAmount(status(), productDisplayPrice: nil)
        let b = SubscriptionPaywallCopy.billedAmount(status(priceDisplay: "NT$170"), productDisplayPrice: "$4.99")
        #expect(a != b)   // loading placeholder is distinct from a real price line
    }

    // MARK: - CTA title price embedding

    @Test func ctaButtonTitle_embedsPriceAndTrial() {
        let withTrial = SubscriptionPaywallCopy.ctaButtonTitle(status(trialDays: 7), productDisplayPrice: "$4.99")
        #expect(withTrial.contains("$4.99"))
        #expect(withTrial.contains("7"))

        let noTrial = SubscriptionPaywallCopy.ctaButtonTitle(status(trialDays: 0), productDisplayPrice: "$4.99")
        #expect(noTrial.contains("$4.99"))
        #expect(!noTrial.contains("7"))

        // No product price → neutral fallback, no price/trial embedded.
        let noPrice = SubscriptionPaywallCopy.ctaButtonTitle(status(trialDays: 7), productDisplayPrice: nil)
        #expect(!noPrice.contains("$"))
    }

    // MARK: - priceLine composition

    @Test func priceLine_appendsTrialWhenPresent() {
        let s = status(trialDays: 7, priceDisplay: "NT$170")
        let line = SubscriptionPaywallCopy.priceLine(s, productDisplayPrice: nil)
        #expect(line.contains("NT$170"))
        #expect(line.contains("·"))   // amount · trial

        // Admin path never appends trial.
        let admin = SubscriptionPaywallCopy.priceLine(status(isActive: true, source: "admin"), productDisplayPrice: nil)
        #expect(!admin.contains("·"))
    }
}
#endif
