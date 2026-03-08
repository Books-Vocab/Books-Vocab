import Foundation
import StoreKit
import CryptoKit

enum SubscriptionPurchaseError: LocalizedError {
    case unverifiedTransaction
    case productNotFound(productID: String)

    var errorDescription: String? {
        switch self {
        case .unverifiedTransaction:
            return "無法驗證 App Store 交易。"
        case .productNotFound(let productID):
            return "App Store 找不到商品 \(productID)。請確認 App Store Connect 的訂閱 Product ID、Bundle ID 與目前測試環境是否一致。"
        }
    }
}

enum PaywallSource: String {
    case settings
    case sync
    case graph
    case reader
    case knowledge
}

@MainActor
protocol SubscriptionManaging: AnyObject {
    var entitlements: KGEntitlements { get }
    var isLoading: Bool { get }
    var lastError: String? { get }
    var activePaywallSource: PaywallSource? { get set }
    var proProduct: Product? { get }
    var proProductIdentifier: String { get }
    var purchaseStatusMessage: String? { get }
    var hasProAccess: Bool { get }

    func refresh(using kgService: any KGServing, authManager: any AuthManaging) async
    func loadProducts() async
    func purchasePro(using kgService: any KGServing, authManager: any AuthManaging) async
    func restorePurchases(using kgService: any KGServing, authManager: any AuthManaging) async
}

@Observable
@MainActor
final class SubscriptionManager: SubscriptionManaging {
    static let shared = SubscriptionManager()
    private static let proProductID = "com.wordnexus.pro.monthly"

    var entitlements = KGEntitlements(
        pro: KGSubscriptionStatus(
            is_active: false,
            product_id: nil,
            plan_name: "BooksBrowser Pro",
            price_display: nil,
            status: "inactive",
            is_trial: false,
            trial_days: 7,
            will_renew: false,
            expires_at: nil,
            source: "app_store",
            last_synced_at: nil
        )
    )
    var isLoading = false
    var lastError: String?
    var activePaywallSource: PaywallSource?
    var proProduct: Product?
    var proProductIdentifier: String { Self.proProductID }
    var purchaseStatusMessage: String?
    var hasProAccess: Bool {
#if DEBUG
        true
#else
        entitlements.pro.is_active
#endif
    }

    private init() {}

    func refresh(using kgService: any KGServing, authManager: any AuthManaging) async {
        guard authManager.isLoggedIn else {
            entitlements = Self.defaultEntitlements
            lastError = nil
            return
        }

        isLoading = true
        defer { isLoading = false }

        do {
            entitlements = try await kgService.fetchEntitlements()
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    func loadProducts() async {
        lastError = nil
        do {
            let products = try await Product.products(for: [Self.proProductID])
            proProduct = products.first
            guard proProduct != nil else {
                throw SubscriptionPurchaseError.productNotFound(productID: Self.proProductID)
            }
            if let product = proProduct, entitlements.pro.price_display == nil {
                entitlements = KGEntitlements(
                    pro: merge(
                        entitlements.pro,
                        priceDisplay: product.displayPrice
                    )
                )
            }
        } catch {
            proProduct = nil
            lastError = error.localizedDescription
        }
    }

    func purchasePro(using kgService: any KGServing, authManager: any AuthManaging) async {
        guard let product = proProduct else {
            purchaseStatusMessage = "尚未取得產品價格，請稍後再試。"
            await loadProducts()
            return
        }
        guard authManager.isLoggedIn else {
            purchaseStatusMessage = "請先登入，再開始免費試用或訂閱。"
            return
        }

        isLoading = true
        defer { isLoading = false }

        do {
            let result = try await product.purchase(options: purchaseOptions(for: authManager.userId))
            switch result {
            case .success(let verification):
                let transaction = try checkVerified(verification)
                await transaction.finish()
                purchaseStatusMessage = "購買成功，正在同步訂閱狀態。"
                entitlements = optimisticEntitlements(from: product, status: inferredStatus(for: product))
                try? await syncTransaction(
                    transaction,
                    signedTransactionInfo: verification.jwsRepresentation,
                    product: product,
                    using: kgService
                )
                await refresh(using: kgService, authManager: authManager)
            case .userCancelled:
                purchaseStatusMessage = "已取消購買。"
            case .pending:
                purchaseStatusMessage = "購買待確認，Apple 完成後會自動更新。"
            @unknown default:
                purchaseStatusMessage = "購買結果未知，請稍後在設定頁重新整理。"
            }
        } catch {
            purchaseStatusMessage = "購買失敗：\(error.localizedDescription)"
            lastError = error.localizedDescription
        }
    }

    func restorePurchases(using kgService: any KGServing, authManager: any AuthManaging) async {
        isLoading = true
        defer { isLoading = false }

        do {
            try await AppStore.sync()
            await syncCurrentEntitlements(using: kgService)
            purchaseStatusMessage = "已向 App Store 要求恢復購買。"
            await refresh(using: kgService, authManager: authManager)
        } catch {
            purchaseStatusMessage = "恢復失敗：\(error.localizedDescription)"
            lastError = error.localizedDescription
        }
    }

    static var defaultEntitlements: KGEntitlements {
        KGEntitlements(
            pro: KGSubscriptionStatus(
                is_active: false,
                product_id: nil,
                plan_name: "BooksBrowser Pro",
                price_display: nil,
                status: "inactive",
                is_trial: false,
                trial_days: 7,
                will_renew: false,
                expires_at: nil,
                source: "app_store",
                last_synced_at: nil
            )
        )
    }

    private func optimisticEntitlements(from product: Product, status: String) -> KGEntitlements {
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

    private func syncCurrentEntitlements(using kgService: any KGServing) async {
        for await result in Transaction.currentEntitlements {
            guard
                let transaction = try? checkVerified(result),
                transaction.productID == Self.proProductID
            else { continue }

            let product = proProduct
            try? await syncTransaction(
                transaction,
                signedTransactionInfo: result.jwsRepresentation,
                product: product,
                using: kgService
            )
            return
        }
    }

    private func syncTransaction(
        _ transaction: Transaction,
        signedTransactionInfo: String?,
        product: Product?,
        using kgService: any KGServing
    ) async throws {
        let environment = appStoreEnvironment(for: transaction)
        let snapshot = KGAppStoreSubscriptionSyncRequest(
            product_id: transaction.productID,
            transaction_id: String(transaction.id),
            original_transaction_id: String(transaction.originalID),
            environment: environment,
            status: inferredStatus(for: product),
            is_trial: entitlements.pro.is_trial,
            expires_at: transaction.expirationDate?.ISO8601Format(),
            will_renew: transaction.revocationDate == nil,
            price_display: product?.displayPrice,
            signed_transaction_info: environment == "xcode" ? nil : signedTransactionInfo
        )
        entitlements = try await kgService.syncAppStoreSubscription(snapshot)
    }

    private func appStoreEnvironment(for transaction: Transaction) -> String {
        switch transaction.environment {
        case .sandbox:
            return "sandbox"
        case .xcode:
            return "xcode"
        default:
            return "production"
        }
    }

    private func inferredStatus(for product: Product?) -> String {
        if entitlements.pro.is_trial {
            return "trial"
        }
        if let product, product.subscription != nil {
            return "active"
        }
        return "active"
    }

    private func merge(
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

    private func purchaseOptions(for userId: String?) -> Set<Product.PurchaseOption> {
        guard let userId, let accountToken = stableUUID(for: userId) else { return [] }
        return [.appAccountToken(accountToken)]
    }

    private func stableUUID(for userId: String) -> UUID? {
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

    private func checkVerified<T>(_ result: VerificationResult<T>) throws -> T {
        switch result {
        case .unverified:
            throw SubscriptionPurchaseError.unverifiedTransaction
        case .verified(let signedType):
            return signedType
        }
    }
}
