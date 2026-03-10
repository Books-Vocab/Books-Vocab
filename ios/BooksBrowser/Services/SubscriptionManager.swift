import Foundation
import StoreKit
import CryptoKit

enum SubscriptionPurchaseError: LocalizedError {
    case unverifiedTransaction
    case productNotFound(productID: String)

    var errorDescription: String? {
        switch self {
        case .unverifiedTransaction:
            return L10n.string("無法驗證 App Store 交易。")
        case .productNotFound(let productID):
            return L10n.format("App Store 找不到商品 %@。請確認 App Store Connect 的訂閱 Product ID、Bundle ID 與目前測試環境是否一致。", productID)
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
        entitlements.pro.is_active
    }

    private var transactionListener: Task<Void, Never>?

    private init() {}

    /// 在 app 啟動時呼叫，持續監聽 Transaction.updates 以捕捉中斷購買、續訂等事件
    func listenForTransactionUpdates(using kgService: any KGServing, authManager: any AuthManaging) {
        transactionListener?.cancel()
        transactionListener = Task(priority: .background) { [weak self] in
            for await result in Transaction.updates {
                guard let self, !Task.isCancelled else { return }
                guard let transaction = try? self.checkVerified(result) else { continue }
                await transaction.finish()
                let product = self.proProduct
                try? await self.syncTransaction(
                    transaction,
                    signedTransactionInfo: result.jwsRepresentation,
                    product: product,
                    using: kgService
                )
                await self.refresh(using: kgService, authManager: authManager)
            }
        }
    }

    func refresh(using kgService: any KGServing, authManager: any AuthManaging) async {
        guard authManager.isLoggedIn else {
            entitlements = Self.defaultEntitlements
            lastError = nil
            return
        }

        isLoading = true
        defer { isLoading = false }

        do {
            var remote = try await kgService.fetchEntitlements()
            // 後端可能不知道用戶已在裝置端取消自動續訂，用 StoreKit 本地狀態覆寫
            if remote.pro.is_active, remote.pro.source != "admin" {
                let willAutoRenew = await queryWillAutoRenew()
                if remote.pro.will_renew != willAutoRenew {
                    remote = KGEntitlements(
                        pro: merge(remote.pro, willRenew: willAutoRenew)
                    )
                }
                // 已過期 + 不續訂 → 本地直接降級，不等後端通知
                if !remote.pro.will_renew, Self.isExpired(remote.pro.expires_at) {
                    print("🔍 [Subscription] locally deactivating: expires_at=\(remote.pro.expires_at ?? "nil") already passed, will_renew=false")
                    remote = KGEntitlements(
                        pro: merge(remote.pro, status: "expired", isActive: false)
                    )
                }
            }
            entitlements = remote
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    private static let productRetryAttempts = 3
    private static let productRetryDelay: UInt64 = 2_000_000_000 // 2s

    func loadProducts() async {
        lastError = nil
        for attempt in 1...Self.productRetryAttempts {
            do {
                let products = try await Product.products(for: [Self.proProductID])
                print("🔍 [StoreKit] attempt \(attempt): returned \(products.count) product(s) for '\(Self.proProductID)'")
                for p in products { print("🔍 [StoreKit] product: \(p.id) — \(p.displayPrice)") }
                if let product = products.first {
                    proProduct = product
                    if entitlements.pro.price_display == nil {
                        entitlements = KGEntitlements(
                            pro: merge(entitlements.pro, priceDisplay: product.displayPrice)
                        )
                    }
                    lastError = nil
                    return
                }
            } catch {
                print("🔍 [StoreKit] attempt \(attempt) error: \(error)")
            }
            if attempt < Self.productRetryAttempts {
                try? await Task.sleep(nanoseconds: Self.productRetryDelay)
            }
        }
        // All retries exhausted — product still unavailable
        proProduct = nil
        lastError = L10n.string("尚未取得訂閱方案，請稍後再試。")
    }

    func purchasePro(using kgService: any KGServing, authManager: any AuthManaging) async {
        guard let product = proProduct else {
            purchaseStatusMessage = L10n.string("尚未取得產品價格，請稍後再試。")
            await loadProducts()
            return
        }
        guard authManager.isLoggedIn else {
            purchaseStatusMessage = L10n.string("請先登入，再開始免費試用或訂閱。")
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
                purchaseStatusMessage = L10n.string("購買成功，正在同步訂閱狀態⋯")
                entitlements = optimisticEntitlements(from: product, status: inferredStatus(for: product))
                do {
                    try await syncTransaction(
                        transaction,
                        signedTransactionInfo: verification.jwsRepresentation,
                        product: product,
                        using: kgService
                    )
                    print("✅ [Subscription] sync succeeded")
                } catch {
                    print("⚠️ [Subscription] sync failed: \(error)")
                }
                await refresh(using: kgService, authManager: authManager)
                if hasProAccess {
                    purchaseStatusMessage = L10n.string("訂閱已啟用，感謝支持！")
                    scheduleClearPurchaseMessage()
                } else {
                    purchaseStatusMessage = L10n.string("Apple 購買成功，但後端同步尚未完成。請稍後點「重新同步」。")
                }
            case .userCancelled:
                purchaseStatusMessage = L10n.string("已取消購買。")
            case .pending:
                purchaseStatusMessage = L10n.string("購買待確認，Apple 完成後會自動更新。")
            @unknown default:
                purchaseStatusMessage = L10n.string("購買結果未知，請稍後在設定頁重新整理。")
            }
        } catch {
            purchaseStatusMessage = L10n.format("購買失敗：%@", error.localizedDescription)
            lastError = error.localizedDescription
        }
    }

    func restorePurchases(using kgService: any KGServing, authManager: any AuthManaging) async {
        isLoading = true
        defer { isLoading = false }

        do {
            try await AppStore.sync()
            await syncCurrentEntitlements(using: kgService)
            await refresh(using: kgService, authManager: authManager)
            if hasProAccess {
                purchaseStatusMessage = L10n.string("購買已恢復，Pro 已啟用。")
            } else {
                purchaseStatusMessage = L10n.string("已向 App Store 恢復購買，但後端尚未同步成功。請稍後再試。")
            }
            scheduleClearPurchaseMessage()
        } catch {
            purchaseStatusMessage = L10n.format("恢復失敗：%@", error.localizedDescription)
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

    private func scheduleClearPurchaseMessage() {
        Task {
            try? await Task.sleep(for: .seconds(4))
            purchaseStatusMessage = nil
        }
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
            do {
                try await syncTransaction(
                    transaction,
                    signedTransactionInfo: result.jwsRepresentation,
                    product: product,
                    using: kgService
                )
                print("✅ [Subscription] currentEntitlements sync succeeded")
            } catch {
                print("⚠️ [Subscription] currentEntitlements sync failed: \(error)")
            }
            return
        }
        print("⚠️ [Subscription] no current entitlement found for \(Self.proProductID)")
    }

    private func syncTransaction(
        _ transaction: Transaction,
        signedTransactionInfo: String?,
        product: Product?,
        using kgService: any KGServing
    ) async throws {
        let environment = appStoreEnvironment(for: transaction)
        let willAutoRenew = await queryWillAutoRenew()
        let snapshot = KGAppStoreSubscriptionSyncRequest(
            product_id: transaction.productID,
            transaction_id: String(transaction.id),
            original_transaction_id: String(transaction.originalID),
            environment: environment,
            status: inferredStatus(for: product),
            is_trial: entitlements.pro.is_trial,
            expires_at: transaction.expirationDate?.ISO8601Format(),
            will_renew: willAutoRenew,
            price_display: product?.displayPrice,
            signed_transaction_info: environment == "xcode" ? nil : signedTransactionInfo
        )
        entitlements = try await kgService.syncAppStoreSubscription(snapshot)
    }

    /// 檢查 ISO8601 到期時間是否已過
    private static func isExpired(_ isoString: String?) -> Bool {
        guard let isoString, !isoString.isEmpty else { return false }
        let f1 = ISO8601DateFormatter()
        f1.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let f2 = ISO8601DateFormatter()
        f2.formatOptions = [.withInternetDateTime]
        guard let date = f1.date(from: isoString) ?? f2.date(from: isoString) else { return false }
        return date < Date()
    }

    /// 從 StoreKit 2 的 Product.SubscriptionInfo 查詢真實的自動續訂狀態
    private func queryWillAutoRenew() async -> Bool {
        guard let product = proProduct, let subscription = product.subscription else {
            print("⚠️ [Subscription] queryWillAutoRenew: no product/subscription info")
            return true
        }
        do {
            let statuses = try await subscription.status
            print("🔍 [Subscription] queryWillAutoRenew: \(statuses.count) status(es)")
            // 優先從 active 狀態取
            for status in statuses where status.state == .subscribed || status.state == .inGracePeriod {
                if let renewalInfo = try? checkVerified(status.renewalInfo) {
                    print("🔍 [Subscription] active state=\(status.state), willAutoRenew=\(renewalInfo.willAutoRenew)")
                    return renewalInfo.willAutoRenew
                }
            }
            // 沒有 active 狀態，從 expired/revoked 取（sandbox 快速過期常見）
            for status in statuses {
                if let renewalInfo = try? checkVerified(status.renewalInfo) {
                    print("🔍 [Subscription] fallback state=\(status.state), willAutoRenew=\(renewalInfo.willAutoRenew)")
                    return renewalInfo.willAutoRenew
                }
            }
            print("⚠️ [Subscription] queryWillAutoRenew: no verified renewalInfo found")
        } catch {
            print("⚠️ [Subscription] queryWillAutoRenew failed: \(error)")
        }
        return true
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
