import Foundation
import StoreKit

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
    case podcast
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

    func refresh(using kgService: any KGServing, authManager: any AuthManaging, force: Bool) async
    func resyncAfterManagement(using kgService: any KGServing, authManager: any AuthManaging) async
    func loadProducts() async
    func purchasePro(using kgService: any KGServing, authManager: any AuthManaging) async
    func restorePurchases(using kgService: any KGServing, authManager: any AuthManaging) async
}

extension SubscriptionManaging {
    func refresh(using kgService: any KGServing, authManager: any AuthManaging) async {
        await refresh(using: kgService, authManager: authManager, force: false)
    }
}

@Observable
@MainActor
final class SubscriptionManager: SubscriptionManaging {
    static let shared = SubscriptionManager()
    static let proProductID = "com.wordnexus.pro.monthly"

    var entitlements = KGEntitlements(
        pro: KGSubscriptionStatus(
            is_active: false,
            product_id: nil,
            plan_name: "Books & Vocab Pro",
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

    var lastRefreshTime: Date?
    static let refreshCooldown: TimeInterval = 2.0

    var transactionListener: Task<Void, Never>?
    var expiryTimer: Task<Void, Never>?

    /// refresh 需要的外部依賴，由 listenForTransactionUpdates 設定
    weak var _kgService: (any KGServing)?
    weak var _authManager: (any AuthManaging)?

    static let productRetryAttempts = 3
    static let productRetryDelay: UInt64 = 2_000_000_000 // 2s

    private init() {}

    static var defaultEntitlements: KGEntitlements {
        KGEntitlements(
            pro: KGSubscriptionStatus(
                is_active: false,
                product_id: nil,
                plan_name: "Books & Vocab Pro",
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

    /// 在 app 啟動時呼叫，持續監聽 Transaction.updates 以捕捉中斷購買、續訂等事件
    func listenForTransactionUpdates(using kgService: any KGServing, authManager: any AuthManaging) {
        _kgService = kgService
        _authManager = authManager
        transactionListener?.cancel()
        transactionListener = Task(priority: .background) { [weak self] in
            for await result in Transaction.updates {
                guard let self, !Task.isCancelled else { return }
                guard let transaction = try? self.checkVerified(result) else { continue }
                await transaction.finish()

                // 只有在使用者已登入時才同步至後端，避免用錯誤帳號的 auth 送出交易
                guard authManager.isLoggedIn else {
                    AppLog.subscription.warning("Transaction update received but no user logged in, skipping sync")
                    continue
                }

                let product = self.proProduct
                do {
                    try await self.syncTransaction(
                        transaction,
                        signedTransactionInfo: result.jwsRepresentation,
                        product: product,
                        using: kgService
                    )
                } catch {
                    AppLog.subscription.error("syncTransaction failed: \(error.localizedDescription)")
                    if !(error is CancellationError) {
                        AppCrashReporting.record(error, context: "subscription.sync.transaction")
                    }
                }
                await self.refresh(using: kgService, authManager: authManager, force: true)
            }
        }
    }
}
