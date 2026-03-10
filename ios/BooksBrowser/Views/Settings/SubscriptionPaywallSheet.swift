import SwiftUI
import StoreKit

struct SubscriptionPaywallSheet: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss
    @Environment(\.subscriptionManager) private var subscriptionManager
    @Environment(\.authManager) private var authManager
    @Environment(\.kgService) private var kgService

    private var windowScene: UIWindowScene {
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first!
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
            .navigationTitle("訂閱")
            .navigationBarTitleDisplayMode(.inline)
            .task {
                await subscriptionManager.loadProducts()
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
            .animation(AppMotion.phaseChange, value: subscriptionManager.hasProAccess)
        }
    }

    // MARK: - 已啟用 Layout（確認式）

    private var activeLayout: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sheetSectionSpacing) {
            // Hero 確認
            VStack(spacing: vocabSkin.spacing.controlGap) {
                Image(systemName: isCancelledButActive ? "exclamationmark.triangle.fill" : "checkmark.seal.fill")
                    .font(.system(size: 48))
                    .foregroundStyle(isCancelledButActive ? vocabSkin.palette.accent : vocabSkin.palette.success)

                Text(isCancelledButActive ? "Pro 即將到期" : "Pro 已啟用")
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
            VStack(alignment: .leading, spacing: vocabSkin.spacing.rowContentSpacing) {
                unlockedFeatureRow("AI 翻譯與語境解釋")
                unlockedFeatureRow("知識庫同步與跨裝置狀態")
                unlockedFeatureRow("關聯圖與內建複習")
            }
            .padding(vocabSkin.spacing.cardPadding)
            .background(vocabSkin.palette.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                    .stroke(vocabSkin.palette.success.opacity(0.2), lineWidth: 1)
            )

            // 來源資訊
            VStack(alignment: .leading, spacing: vocabSkin.spacing.microGap) {
                Text(priceLine)
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(vocabSkin.palette.primaryText)
                Text(L10n.format("權限來源：%@", entitlementSourceLine))
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            }

            // 管理按鈕
            VStack(spacing: vocabSkin.spacing.controlGap) {
                if !isAdminGranted {
                    Button {
                        Task {
                            try? await AppStore.showManageSubscriptions(in: windowScene)
                        }
                    } label: {
                        HStack {
                            Text("管理訂閱")
                            Spacer()
                            Image(systemName: "arrow.up.forward")
                                .font(vocabSkin.typography.iconSmall)
                                .foregroundStyle(vocabSkin.palette.quaternaryText)
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.vocabAction(.primary))
                }

                Button {
                    Task {
                        await subscriptionManager.refresh(using: kgService, authManager: authManager)
                    }
                } label: {
                    HStack {
                        if subscriptionManager.isLoading {
                            ProgressView().controlSize(.small)
                        }
                        Text(primaryActionTitle)
                        Spacer()
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.vocabAction(.neutral))
                .disabled(subscriptionManager.isLoading)
            }

            if let purchaseStatusMessage = subscriptionManager.purchaseStatusMessage {
                VocabStateMessageCard(
                    title: purchaseStatusMessage,
                    systemImage: "checkmark.circle"
                )
            }

            Text(footerNote)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
        }
        .padding(vocabSkin.spacing.sheetPaddingCompact)
    }

    // MARK: - 未啟用 Layout（行銷式）

    private var inactiveLayout: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sheetSectionSpacing) {
            Image(systemName: "sparkles.rectangle.stack.fill")
                .font(vocabSkin.typography.symbolHero)
                .foregroundStyle(vocabSkin.palette.accent)

            Text("BooksBrowser Pro")
                .font(vocabSkin.typography.displayTitle)
                .foregroundStyle(vocabSkin.palette.primaryText)

            Text(paywallSummaryText)
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .lineSpacing(6)

            // 價格區塊（突出）
            VStack(alignment: .leading, spacing: vocabSkin.spacing.microGap) {
                Text(priceLine)
                    .font(vocabSkin.typography.sectionTitle)
                    .foregroundStyle(vocabSkin.palette.primaryText)
                Text(L10n.format("權限來源：%@", entitlementSourceLine))
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            }

            // 功能列（行銷式 — 強調你「缺少」什麼）
            VStack(alignment: .leading, spacing: vocabSkin.spacing.rowContentSpacing) {
                lockedFeatureRow("AI 翻譯與語境解釋", description: "閱讀時即時查詢翻譯與語境")
                lockedFeatureRow("知識庫同步與跨裝置狀態", description: "生詞與閱讀進度跨裝置同步")
                lockedFeatureRow("關聯圖與內建複習", description: "視覺化詞彙關聯與間隔複習")
            }
            .padding(vocabSkin.spacing.cardPadding)
            .background(vocabSkin.palette.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                    .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
            )

            // CTA 按鈕（強烈）
            VStack(spacing: vocabSkin.spacing.controlGap) {
                Button {
                    Task {
                        await subscriptionManager.purchasePro(using: kgService, authManager: authManager)
                    }
                } label: {
                    HStack {
                        if subscriptionManager.isLoading {
                            ProgressView().controlSize(.small)
                        }
                        Text("開始免費試用")
                        Spacer()
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.vocabAction(.primary))
                .disabled(subscriptionManager.isLoading)

                Button {
                    Task {
                        await subscriptionManager.restorePurchases(using: kgService, authManager: authManager)
                    }
                } label: {
                    Text("恢復購買")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.vocabAction(.neutral))
                .disabled(subscriptionManager.isLoading)
            }

            if let purchaseStatusMessage = subscriptionManager.purchaseStatusMessage {
                VocabStateMessageCard(
                    title: purchaseStatusMessage,
                    systemImage: "checkmark.circle"
                )
            }

            if subscriptionManager.proProduct == nil, subscriptionManager.lastError != nil {
                VocabStateMessageCard(
                    title: "訂閱方案載入中",
                    systemImage: "arrow.clockwise.circle",
                    description: "App Store 尚未回傳訂閱資訊，請稍候或點下方重試。"
                ) {
                    Button {
                        Task { await subscriptionManager.loadProducts() }
                    } label: {
                        Text("重新載入")
                            .font(vocabSkin.typography.caption)
                    }
                    .buttonStyle(.vocabAction(.neutral))
                    .disabled(subscriptionManager.isLoading)
                }
            }

            Text(footerNote)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
        }
        .padding(vocabSkin.spacing.sheetPaddingCompact)
    }

    // MARK: - Feature Rows

    private func unlockedFeatureRow(_ text: String) -> some View {
        HStack(spacing: vocabSkin.spacing.controlGap) {
            Image(systemName: "checkmark.circle.fill")
                .font(vocabSkin.typography.iconMedium)
                .foregroundStyle(vocabSkin.palette.success)
            Text(text)
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.primaryText)
            Spacer()
        }
    }

    private func lockedFeatureRow(_ title: String, description: String) -> some View {
        HStack(alignment: .top, spacing: vocabSkin.spacing.controlGap) {
            Image(systemName: "sparkles")
                .font(vocabSkin.typography.iconMedium)
                .foregroundStyle(vocabSkin.palette.accent)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(vocabSkin.typography.body.weight(.medium))
                    .foregroundStyle(vocabSkin.palette.primaryText)
                Text(description)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            }
            Spacer()
        }
    }

    // MARK: - Computed Properties

    private var isCancelledButActive: Bool {
        subscriptionManager.hasProAccess
            && !subscriptionManager.entitlements.pro.will_renew
            && subscriptionManager.entitlements.pro.source != "admin"
    }

    private var activeSummaryText: String {
        if isAdminGranted {
            return L10n.string("目前帳號已由管理員授權為 Pro。")
        }
        if isCancelledButActive {
            let expiry = SettingsView.formattedExpiry(subscriptionManager.entitlements.pro.expires_at)
            return L10n.format("你已取消自動續訂。Pro 功能可使用至 %@。", expiry)
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
