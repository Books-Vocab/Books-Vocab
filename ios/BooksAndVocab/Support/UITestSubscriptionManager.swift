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
        guard let seed = FixtureDatasetStore.entitlementsSeed(for: .pro) else {
            preconditionFailure("entitlements.pro fixture requires UI World entitlements.pro")
        }
        return UITestSubscriptionManager(entitlements: KGEntitlements(pro: seed.pro))
    }

    static func freeAccess() -> UITestSubscriptionManager {
        guard let seed = FixtureDatasetStore.entitlementsSeed(for: .free) else {
            preconditionFailure("entitlements.free fixture requires UI World entitlements.free")
        }
        return UITestSubscriptionManager(entitlements: KGEntitlements(pro: seed.pro))
    }

    func refresh(using kgService: any KGServing, authManager: any AuthManaging, force: Bool) async {}
    func resyncAfterManagement(using kgService: any KGServing, authManager: any AuthManaging) async {}
    func loadProducts() async {}
    func purchasePro(using kgService: any KGServing, authManager: any AuthManaging) async {}
    func restorePurchases(using kgService: any KGServing, authManager: any AuthManaging) async {}
    func listenForTransactionUpdates(using kgService: any KGServing, authManager: any AuthManaging) {}
}
#endif
