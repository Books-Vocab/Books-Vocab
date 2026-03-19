import SwiftUI
import StoreKit

struct SubscriptionPaywallSheet: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss
    @Environment(\.subscriptionManager) private var subscriptionManager
    @Environment(\.authManager) private var authManager
    @Environment(\.kgService) private var kgService

    private var windowScene: UIWindowScene? {
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first
    }

    private var activeFeatures: [SettingsSubscriptionFeatureItem] {
        [
            .init(
                title: "AI 翻譯與語境解釋".localized,
                description: nil,
                icon: "checkmark.circle.fill",
                tone: vocabSkin.palette.success
            ),
            .init(
                title: "知識庫同步與跨裝置狀態".localized,
                description: nil,
                icon: "checkmark.circle.fill",
                tone: vocabSkin.palette.success
            ),
            .init(
                title: "關聯圖與內建複習".localized,
                description: nil,
                icon: "checkmark.circle.fill",
                tone: vocabSkin.palette.success
            )
        ]
    }

    private var paywallFeatures: [SettingsSubscriptionFeatureItem] {
        [
            .init(
                title: "AI 翻譯與語境解釋".localized,
                description: "閱讀時即時查詢翻譯與語境".localized,
                icon: "sparkles",
                tone: vocabSkin.palette.accent
            ),
            .init(
                title: "知識庫同步與跨裝置狀態".localized,
                description: "生詞與閱讀進度跨裝置同步".localized,
                icon: "sparkles",
                tone: vocabSkin.palette.accent
            ),
            .init(
                title: "關聯圖與內建複習".localized,
                description: "視覺化詞彙關聯與間隔複習".localized,
                icon: "sparkles",
                tone: vocabSkin.palette.accent
            )
        ]
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                if subscriptionManager.hasProAccess {
                    activeLayout
                } else {
                    inactiveLayout
                }
            }
            .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
            .navigationTitle("訂閱".localized)
            .navigationBarTitleDisplayMode(.inline)
            .task {
                await subscriptionManager.loadProducts()
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成".localized) { dismiss() }
                }
            }
            .animatePhaseChange(subscriptionManager.hasProAccess)
            .animatePhaseChange(subscriptionManager.entitlements.pro.will_renew)
        }
    }

    // MARK: - 已啟用 Layout（確認式）

    private var activeLayout: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sheetSectionSpacing) {
            // Hero 確認
            VStack(spacing: vocabSkin.spacing.controlGap) {
                Image(systemName: isCancelledButActive ? "exclamationmark.triangle.fill" : "checkmark.seal.fill")
                    .font(vocabSkin.typography.symbolHero)
                    .foregroundStyle(isCancelledButActive ? vocabSkin.palette.accent : vocabSkin.palette.success)

                Text(isCancelledButActive ? "Pro 即將到期".localized : "Pro 已啟用".localized)
                    .font(vocabSkin.typography.displayTitle)
                    .foregroundStyle(vocabSkin.palette.primaryText)

                Text(activeSummaryText)
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
                    .multilineTextAlignment(.center)
                    .lineSpacing(4)
            }
            .frame(maxWidth: .infinity)
            .padding(.top, vocabSkin.spacing.inlineGap)

            // 功能已解鎖列表
            SettingsSubscriptionFeatureList(
                borderTone: vocabSkin.palette.success.opacity(0.2),
                items: activeFeatures
            )

            // 來源資訊
            SettingsSubscriptionInfoBlock(
                title: priceLine,
                detail: L10n.format("權限來源：%@", entitlementSourceLine),
                titleFont: vocabSkin.typography.captionStrong
            )

            // 管理按鈕
            VStack(spacing: vocabSkin.spacing.controlGap) {
                if !isAdminGranted {
                    Button {
                        Task {
                            guard let scene = windowScene else { return }
                            try? await AppStore.showManageSubscriptions(in: scene)
                            await subscriptionManager.resyncAfterManagement(using: kgService, authManager: authManager)
                        }
                    } label: {
                        paywallActionLabel(
                            title: "管理訂閱".localized,
                            trailingSystemImage: "arrow.up.forward"
                        )
                    }
                    .buttonStyle(.vocabAction(.primary))
                }

                Button {
                    Task {
                        await subscriptionManager.refresh(using: kgService, authManager: authManager, force: true)
                    }
                } label: {
                    paywallActionLabel(
                        title: primaryActionTitle,
                        isLoading: subscriptionManager.isLoading
                    )
                }
                .buttonStyle(.vocabAction(.neutral))
                .disabled(subscriptionManager.isLoading)
            }

            purchaseStatusCard

            Text(footerNote)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.tertiaryText)

            legalLinksFooter
        }
        .padding(vocabSkin.spacing.sheetPaddingCompact)
    }

    // MARK: - 未啟用 Layout（行銷式）

    private var inactiveLayout: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sheetSectionSpacing) {
            Image(systemName: "sparkles.rectangle.stack.fill")
                .font(vocabSkin.typography.symbolHero)
                .foregroundStyle(vocabSkin.palette.accent)

            Text("Books & Vocab Pro")
                .font(vocabSkin.typography.displayTitle)
                .foregroundStyle(vocabSkin.palette.primaryText)

            Text(paywallSummaryText)
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .lineSpacing(6)

            // 價格區塊（突出）
            SettingsSubscriptionInfoBlock(
                title: priceLine,
                detail: L10n.format("權限來源：%@", entitlementSourceLine),
                titleFont: vocabSkin.typography.sectionTitle
            )

            // 功能列（行銷式 — 強調你「缺少」什麼）
            SettingsSubscriptionFeatureList(
                borderTone: vocabSkin.palette.cardBorder,
                items: paywallFeatures
            )

            // CTA 按鈕（強烈）
            VStack(spacing: vocabSkin.spacing.controlGap) {
                Button {
                    Task {
                        await subscriptionManager.purchasePro(using: kgService, authManager: authManager)
                    }
                } label: {
                    paywallActionLabel(
                        title: "開始免費試用".localized,
                        isLoading: subscriptionManager.isLoading
                    )
                }
                .buttonStyle(.vocabAction(.primary))
                .disabled(subscriptionManager.isLoading)

                Button {
                    Task {
                        await subscriptionManager.restorePurchases(using: kgService, authManager: authManager)
                    }
                } label: {
                    paywallActionLabel(title: "恢復購買".localized)
                }
                .buttonStyle(.vocabAction(.neutral))
                .disabled(subscriptionManager.isLoading)
            }

            purchaseStatusCard

            if subscriptionManager.proProduct == nil, subscriptionManager.lastError != nil {
                loadProductsRetryCard
            }

            Text(footerNote)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.tertiaryText)

            Text(L10n.string("訂閱將透過 Apple ID 自動續訂。可隨時在 App Store 設定中取消，取消後當期仍可使用至到期日。"))
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .multilineTextAlignment(.leading)

            legalLinksFooter
        }
        .padding(vocabSkin.spacing.sheetPaddingCompact)
    }

    @ViewBuilder
    private var purchaseStatusCard: some View {
        if let purchaseStatusMessage = subscriptionManager.purchaseStatusMessage {
            VocabStateMessageCard(
                title: purchaseStatusMessage,
                systemImage: "checkmark.circle"
            )
        }
    }

    private var loadProductsRetryCard: some View {
        VocabStateMessageCard(
            title: "訂閱方案載入中".localized,
            systemImage: "arrow.clockwise.circle",
            description: "App Store 尚未回傳訂閱資訊，請稍候或點下方重試。".localized
        ) {
            Button {
                Task { await subscriptionManager.loadProducts() }
            } label: {
                paywallActionLabel(title: "重新載入".localized, font: vocabSkin.typography.caption)
            }
            .buttonStyle(.vocabAction(.neutral))
            .disabled(subscriptionManager.isLoading)
        }
    }

    private func paywallActionLabel(
        title: String,
        isLoading: Bool = false,
        trailingSystemImage: String? = nil,
        font: Font? = nil
    ) -> some View {
        HStack {
            if isLoading {
                ProgressView().controlSize(.small)
            }

            Text(title)
                .font(font)

            Spacer()

            if let trailingSystemImage {
                Image(systemName: trailingSystemImage)
                    .font(vocabSkin.typography.iconSmall)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
            }
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Legal Links Footer

    private var legalLinksFooter: some View {
        HStack(spacing: vocabSkin.spacing.controlGap) {
            Link(L10n.string("隱私政策"), destination: AppURLs.privacy)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
            Text("·")
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
            Link(L10n.string("服務條款"), destination: AppURLs.terms)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
            Spacer()
        }
    }

    // MARK: - Computed Properties

    private var isCancelledButActive: Bool {
        subscriptionManager.entitlements.pro.isCancelledButActive
    }

    private var activeSummaryText: String {
        if isAdminGranted {
            return L10n.string("目前帳號已由管理員授權為 Pro。")
        }
        if isCancelledButActive {
            return L10n.format("你已取消自動續訂。Pro 功能可使用至 %@。", subscriptionManager.entitlements.pro.formattedExpiryDate)
        }
        return L10n.string("感謝支持！所有進階功能已解鎖。")
    }

    private var paywallSummaryText: String {
        return L10n.string("解鎖閱讀器 AI、知識庫同步、關聯圖與內建複習。免費試用與價格會直接來自 App Store。")
    }

    private var priceLine: String {
        if isAdminGranted {
            if let expiresAt = subscriptionManager.entitlements.pro.expires_at, !expiresAt.isEmpty {
                return L10n.format("管理員授權 · 有效至 %@", expiresAt)
            }
            return L10n.string("管理員授權")
        }
        if let product = subscriptionManager.proProduct {
            let days = subscriptionManager.entitlements.pro.trial_days ?? 7
            return L10n.format("%@ / month · %@ 天免費試用", product.displayPrice, "\(days)")
        }
        if let remotePrice = subscriptionManager.entitlements.pro.price_display, !remotePrice.isEmpty {
            return remotePrice
        }
        return L10n.string("載入 App Store 價格中…")
    }

    private var entitlementSourceLine: String {
        switch subscriptionManager.entitlements.pro.source {
        case "admin":
            return L10n.string("管理員授權")
        default:
            return L10n.string("App Store 訂閱")
        }
    }

    private var isAdminGranted: Bool {
        subscriptionManager.entitlements.pro.is_active && subscriptionManager.entitlements.pro.source == "admin"
    }

    private var primaryActionTitle: String {
        if isAdminGranted {
            return L10n.string("重新整理權限狀態")
        }
        return L10n.string("重新同步訂閱狀態")
    }

    private var footerNote: String {
        if isAdminGranted {
            return L10n.string("此帳號目前由管理員授權為 Pro；若需延長、撤銷或調整，請聯絡管理員。")
        }
        if isCancelledButActive {
            return L10n.string("到期後將回到免費方案。如需繼續使用 Pro，可重新訂閱。")
        }
        return L10n.string("價格與免費試用長度會以 App Store 與你的地區顯示為準。")
    }
}
