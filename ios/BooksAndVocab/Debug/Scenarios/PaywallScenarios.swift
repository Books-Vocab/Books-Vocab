#if DEBUG && canImport(Playbook)
import Playbook
import StoreKit
import SwiftUI

/// Catalog scenarios for `SubscriptionPaywallSheet`.
///
/// The sheet derives every piece of copy from `subscriptionManager.entitlements.pro`
/// via the pure `SubscriptionPaywallCopy` enum, and branches its whole layout on
/// `subscriptionManager.hasProAccess`. So we drive the surface entirely through a
/// synthetic `PreviewSubscriptionManager` mock — no network, no StoreKit.
///
/// `SubscriptionManaging` is `@MainActor`-isolated, so the mock is constructed
/// inside a `View` body (`PaywallScene`), never synchronously inside a `Scenario`
/// closure.
enum PaywallScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Paywall") {
            Scenario("Paywall (inactive)", layout: .fill) {
                PaywallScene(status: PaywallScenarios.inactiveStatus)
            }
            Scenario("Pro active (renewing)", layout: .fill) {
                PaywallScene(status: PaywallScenarios.activeRenewingStatus)
            }
            Scenario("Pro cancelled but active", layout: .fill) {
                PaywallScene(status: PaywallScenarios.cancelledButActiveStatus)
            }
            Scenario("Admin granted", layout: .fill) {
                PaywallScene(status: PaywallScenarios.adminGrantedStatus)
            }
        }
    }

    // MARK: - Fixtures

    private static func makeStatus(
        is_active: Bool,
        status: String,
        is_trial: Bool = false,
        will_renew: Bool,
        expires_at: String? = nil,
        source: String = "app_store",
        price_display: String? = nil
    ) -> KGSubscriptionStatus {
        KGSubscriptionStatus(
            is_active: is_active,
            product_id: is_active ? BrandIdentity.proProductID : nil,
            plan_name: "Books & Vocab Pro",
            price_display: price_display,
            status: status,
            is_trial: is_trial,
            trial_days: 7,
            will_renew: will_renew,
            expires_at: expires_at,
            source: source,
            last_synced_at: "2026-06-01T08:00:00Z"
        )
    }

    static let inactiveStatus = makeStatus(
        is_active: false,
        status: "inactive",
        will_renew: false
    )

    static let activeRenewingStatus = makeStatus(
        is_active: true,
        status: "active",
        will_renew: true,
        expires_at: "2026-07-01T08:00:00Z",
        price_display: "NT$90 / 月"
    )

    static let cancelledButActiveStatus = makeStatus(
        is_active: true,
        status: "active",
        will_renew: false,
        expires_at: "2026-06-20T08:00:00Z",
        price_display: "NT$90 / 月"
    )

    static let adminGrantedStatus = makeStatus(
        is_active: true,
        status: "active",
        will_renew: true,
        expires_at: nil,
        source: "admin"
    )
}

// MARK: - Scene harness

/// Builds the `@MainActor` mock inside a main-actor-isolated `body`, then injects
/// it into the sheet's environment.
private struct PaywallScene: View {
    let status: KGSubscriptionStatus

    var body: some View {
        AppThemeContainer {
            SubscriptionPaywallSheet()
                .environment(\.subscriptionManager, PreviewSubscriptionManager(status: status))
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

// MARK: - Mock

/// Inert `SubscriptionManaging` for catalog rendering. All async actions are no-ops.
@MainActor
private final class PreviewSubscriptionManager: SubscriptionManaging {
    var entitlements: KGEntitlements
    var isLoading: Bool = false
    var lastError: String?
    var activePaywallSource: PaywallSource?
    var proProduct: Product?
    var proProductIdentifier: String = BrandIdentity.proProductID
    var purchaseStatusMessage: String?

    var hasProAccess: Bool { entitlements.pro.is_active }

    init(status: KGSubscriptionStatus) {
        self.entitlements = KGEntitlements(pro: status)
    }

    func refresh(using kgService: any KGServing, authManager: any AuthManaging, force: Bool) async {}
    func resyncAfterManagement(using kgService: any KGServing, authManager: any AuthManaging) async {}
    func loadProducts() async {}
    func purchasePro(using kgService: any KGServing, authManager: any AuthManaging) async {}
    func restorePurchases(using kgService: any KGServing, authManager: any AuthManaging) async {}
}
#endif
