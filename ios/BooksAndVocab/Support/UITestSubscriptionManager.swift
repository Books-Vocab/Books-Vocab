#if DEBUG
import Foundation
import StoreKit

@MainActor
final class UITestSubscriptionManager: SubscriptionManaging {
    var entitlements: KGEntitlements
    var isLoading = false
    var lastError: String?
    var activePaywallSource: PaywallSource?
    var proProduct: Product?
    var proProductIdentifier: String = BrandIdentity.proProductID
    var purchaseStatusMessage: String?

    var hasProAccess: Bool { entitlements.pro.is_active }

    private init(entitlements: KGEntitlements) {
        self.entitlements = entitlements
    }

    static func proAccess() -> UITestSubscriptionManager {
        UITestSubscriptionManager(
            entitlements: KGEntitlements(
                pro: KGSubscriptionStatus(
                    is_active: true,
                    product_id: BrandIdentity.proProductID,
                    plan_name: "Books & Vocab Pro",
                    price_display: "NT$90 / month",
                    status: "active",
                    is_trial: false,
                    trial_days: 7,
                    will_renew: true,
                    expires_at: "2099-12-31T23:59:59Z",
                    source: "app_store",
                    last_synced_at: "2026-06-10T00:00:00Z"
                )
            )
        )
    }

    func refresh(using kgService: any KGServing, authManager: any AuthManaging, force: Bool) async {}
    func resyncAfterManagement(using kgService: any KGServing, authManager: any AuthManaging) async {}
    func loadProducts() async {}
    func purchasePro(using kgService: any KGServing, authManager: any AuthManaging) async {}
    func restorePurchases(using kgService: any KGServing, authManager: any AuthManaging) async {}
    func listenForTransactionUpdates(using kgService: any KGServing, authManager: any AuthManaging) {}
}
#endif
