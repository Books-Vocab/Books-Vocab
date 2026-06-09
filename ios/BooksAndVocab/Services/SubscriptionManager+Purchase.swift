import StoreKit

extension SubscriptionManager {
    func loadProducts() async {
        lastError = nil
        for attempt in 1...Self.productRetryAttempts {
            do {
                let products = try await Product.products(for: [Self.proProductID])
                AppLog.subscription.debug("StoreKit attempt \(attempt): returned \(products.count) product(s) for '\(Self.proProductID)'")
                for p in products { AppLog.subscription.debug("StoreKit product: \(p.id) — \(p.displayPrice)") }
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
                AppLog.subscription.debug("StoreKit attempt \(attempt) error: \(error.localizedDescription)")
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
                    AppLog.subscription.info("Sync succeeded")
                } catch {
                    AppLog.subscription.warning("Sync failed: \(error.localizedDescription)")
                    if !(error is CancellationError) {
                        AppCrashReporting.record(error, context: "subscription.purchase.sync")
                    }
                }
                await refresh(using: kgService, authManager: authManager, force: true)
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
            // Filter StoreKit user-cancel and offline: those are recoverable / user-driven
            if !(error is CancellationError),
               !(error is StoreKitError) {
                AppCrashReporting.record(error, context: "subscription.purchase")
            }
        }
    }

    func restorePurchases(using kgService: any KGServing, authManager: any AuthManaging) async {
        isLoading = true
        defer { isLoading = false }

        do {
            try await AppStore.sync()
            await syncCurrentEntitlements(using: kgService)
            await refresh(using: kgService, authManager: authManager, force: true)
            if hasProAccess {
                purchaseStatusMessage = L10n.string("購買已恢復，Pro 已啟用。")
            } else {
                purchaseStatusMessage = L10n.string("已向 App Store 恢復購買，但後端尚未同步成功。請稍後再試。")
            }
            scheduleClearPurchaseMessage()
        } catch {
            purchaseStatusMessage = L10n.format("恢復失敗：%@", error.localizedDescription)
            lastError = error.localizedDescription
            if !(error is CancellationError) {
                AppCrashReporting.record(error, context: "subscription.restore")
            }
        }
    }
}
