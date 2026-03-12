import StoreKit
import CryptoKit

extension SubscriptionManager {
    func inferredStatus(for product: Product?) -> String {
        if entitlements.pro.is_trial {
            return "trial"
        }
        if let product, product.subscription != nil {
            return "active"
        }
        return "active"
    }

    func merge(
        _ status: KGSubscriptionStatus,
        productId: String? = nil,
        priceDisplay: String? = nil,
        status newStatus: String? = nil,
        isActive: Bool? = nil,
        isTrial: Bool? = nil,
        willRenew: Bool? = nil
    ) -> KGSubscriptionStatus {
        KGSubscriptionStatus(
            is_active: isActive ?? status.is_active,
            product_id: productId ?? status.product_id,
            plan_name: status.plan_name,
            price_display: priceDisplay ?? status.price_display,
            status: newStatus ?? status.status,
            is_trial: isTrial ?? status.is_trial,
            trial_days: status.trial_days,
            will_renew: willRenew ?? status.will_renew,
            expires_at: status.expires_at,
            source: status.source,
            last_synced_at: status.last_synced_at
        )
    }

    func optimisticEntitlements(from product: Product, status: String) -> KGEntitlements {
        KGEntitlements(
            pro: merge(
                entitlements.pro,
                productId: product.id,
                priceDisplay: product.displayPrice,
                status: status,
                isActive: true,
                isTrial: entitlements.pro.is_trial || status == "trial",
                willRenew: true
            )
        )
    }

    func purchaseOptions(for userId: String?) -> Set<Product.PurchaseOption> {
        guard let userId, let accountToken = stableUUID(for: userId) else { return [] }
        return [.appAccountToken(accountToken)]
    }

    func stableUUID(for userId: String) -> UUID? {
        let digest = SHA256.hash(data: Data(userId.utf8))
        let bytes = Array(digest.prefix(16))
        guard bytes.count == 16 else { return nil }

        let uuidString = String(
            format: "%02X%02X%02X%02X-%02X%02X-%02X%02X-%02X%02X-%02X%02X%02X%02X%02X%02X",
            bytes[0], bytes[1], bytes[2], bytes[3],
            bytes[4], bytes[5],
            bytes[6], bytes[7],
            bytes[8], bytes[9],
            bytes[10], bytes[11], bytes[12], bytes[13], bytes[14], bytes[15]
        )
        return UUID(uuidString: uuidString)
    }

    func checkVerified<T>(_ result: VerificationResult<T>) throws -> T {
        switch result {
        case .unverified:
            throw SubscriptionPurchaseError.unverifiedTransaction
        case .verified(let signedType):
            return signedType
        }
    }

    func scheduleClearPurchaseMessage() {
        Task {
            try? await Task.sleep(for: .seconds(4))
            purchaseStatusMessage = nil
        }
    }
}
