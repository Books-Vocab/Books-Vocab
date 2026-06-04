import SwiftUI
import StoreKit
import Inject

struct SubscriptionPaywallSheet: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.dismiss) private var dismiss
    @Environment(\.subscriptionManager) private var subscriptionManager
    @Environment(\.authManager) private var authManager
    @Environment(\.kgService) private var kgService


    private var activeFeatures: [SettingsSubscriptionFeatureItem] {
        [
            .init(
                title: "AI 翻譯與語境解釋".localized,
                description: nil,
                icon: "checkmark.circle.fill",
                tone: appSkin.palette.success
            ),
            .init(
                title: "雲端同步與跨裝置狀態".localized,
                description: nil,
                icon: "checkmark.circle.fill",
                tone: appSkin.palette.success
            ),
            .init(
                title: "關聯圖與內建複習".localized,
                description: nil,
                icon: "checkmark.circle.fill",
                tone: appSkin.palette.success
            )
        ]
    }

    private var paywallFeatures: [SettingsSubscriptionFeatureItem] {
        [
            .init(
                title: "AI 翻譯與語境解釋".localized,
                description: "閱讀時即時查詢翻譯與語境".localized,
                icon: "sparkles",
                tone: appSkin.palette.accent
            ),
            .init(
                title: "雲端同步與跨裝置狀態".localized,
                description: "生詞與閱讀進度跨裝置同步".localized,
                icon: "sparkles",
                tone: appSkin.palette.accent
            ),
            .init(
                title: "關聯圖與內建複習".localized,
                description: "視覺化詞彙關聯與間隔複習".localized,
                icon: "sparkles",
                tone: appSkin.palette.accent
            )
        ]
    }

    /// Free vs Pro 對照表 — 強化升級決策資訊密度
    private var comparisonRows: [SettingsPlanComparisonRow] {
        [
            .init(
                title: "閱讀器（EPUB/PDF/TXT/MD）".localized,
                freeMark: .check,
                proMark: .check
            ),
            .init(
                title: "本地生詞捕捉".localized,
                freeMark: .check,
                proMark: .check
            ),
            .init(
                title: "AI 翻譯與語境解釋".localized,
                freeMark: .label("有限".localized),
                proMark: .check
            ),
            .init(
                title: "雲端同步與跨裝置狀態".localized,
                freeMark: .label("有限".localized),
                proMark: .check
            ),
            .init(
                title: "知識圖譜與關聯卡片".localized,
                freeMark: .label("有限".localized),
                proMark: .check
            ),
            .init(
                title: "間隔複習（Today Review）".localized,
                freeMark: .label("有限".localized),
                proMark: .check
            ),
            .init(
                title: "Podcast 跨集播放".localized,
                freeMark: .label("有限".localized),
                proMark: .check
            ),
            .init(
                title: "每日 AI 額度".localized,
                freeMark: .label("1x"),
                proMark: .label("10x")
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
            .background(appSkin.palette.pageBackground.ignoresSafeArea())
            .navigationTitle("訂閱".localized)
            .inlineNavigationBarTitle()
            .task {
                await subscriptionManager.loadProducts()
            }
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成".localized) { dismiss() }
                }
            }
            .animatePhaseChange(subscriptionManager.hasProAccess)
            .animatePhaseChange(subscriptionManager.entitlements.pro.will_renew)
        }
        .enableInjection()
    }

    // MARK: - 已啟用 Layout（確認式）

    private var activeLayout: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sheetSectionSpacing) {
            // Hero 確認
            VStack(spacing: appSkin.spacing.controlGap) {
                Image(systemName: isCancelledButActive ? "exclamationmark.triangle.fill" : "checkmark.seal.fill")
                    .font(appSkin.typography.symbolHero)
                    .foregroundStyle(isCancelledButActive ? appSkin.palette.accent : appSkin.palette.success)

                Text(isCancelledButActive ? "Pro 即將到期".localized : "Pro 已啟用".localized)
                    .font(appSkin.typography.displayTitle)
                    .foregroundStyle(appSkin.palette.primaryText)

                Text(activeSummaryText)
                    .font(appSkin.typography.body)
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .multilineTextAlignment(.center)
                    .lineSpacing(4)
            }
            .frame(maxWidth: .infinity)
            .padding(.top, appSkin.spacing.inlineGap)

            // 功能已解鎖列表
            SettingsSubscriptionFeatureList(
                borderTone: appSkin.palette.success.opacity(0.2),
                items: activeFeatures
            )

            // 來源資訊
            SettingsSubscriptionInfoBlock(
                title: priceLine,
                detail: L10n.format("權限來源：%@", entitlementSourceLine),
                titleFont: appSkin.typography.caption
            )

            // 管理按鈕
            VStack(spacing: appSkin.spacing.controlGap) {
                if !isAdminGranted {
                    Button {
                        Task {
                            await PlatformStore.manageSubscriptions()
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
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)

            legalLinksFooter
        }
        .padding(appSkin.spacing.sheetPaddingCompact)
    }

    // MARK: - 未啟用 Layout（行銷式）

    private var inactiveLayout: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sheetSectionSpacing) {
            Image(systemName: "sparkles.rectangle.stack.fill")
                .font(appSkin.typography.symbolHero)
                .foregroundStyle(appSkin.palette.accent)

            Text("Books & Vocab Pro")
                .font(appSkin.typography.displayTitle)
                .foregroundStyle(appSkin.palette.primaryText)

            Text(paywallSummaryText)
                .font(appSkin.typography.body)
                .foregroundStyle(appSkin.palette.secondaryText)
                .lineSpacing(6)

            // 價格區塊（金額最突出，試用為次要 — 3.1.2(c) 合規）
            SettingsSubscriptionInfoBlock(
                title: billedAmountLine,
                subtitle: trialInfoLine,
                detail: L10n.format("權限來源：%@", entitlementSourceLine),
                titleFont: appSkin.typography.sectionTitle
            )

            // 功能列（行銷式 — 強調你「缺少」什麼）
            SettingsSubscriptionFeatureList(
                borderTone: appSkin.palette.cardBorder,
                items: paywallFeatures
            )

            // Free vs Pro 對照表
            SettingsPlanComparisonTable(rows: comparisonRows)

            // CTA 按鈕（強烈）
            VStack(spacing: appSkin.spacing.controlGap) {
                Button {
                    Task {
                        await subscriptionManager.purchasePro(using: kgService, authManager: authManager)
                    }
                } label: {
                    paywallActionLabel(
                        title: ctaButtonTitle,
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
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)

            Text(L10n.string("訂閱將透過 Apple ID 自動續訂。可隨時在 App Store 設定中取消，取消後當期仍可使用至到期日。"))
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)
                .multilineTextAlignment(.leading)

            legalLinksFooter
        }
        .padding(appSkin.spacing.sheetPaddingCompact)
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
                paywallActionLabel(title: "重新載入".localized, font: appSkin.typography.caption)
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
                    .font(appSkin.typography.iconSmall)
                    .foregroundStyle(appSkin.palette.quaternaryText)
            }
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Legal Links Footer

    private var legalLinksFooter: some View {
        HStack(spacing: appSkin.spacing.controlGap) {
            Link(L10n.string("隱私政策"), destination: AppURLs.privacy)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)
            Text("·")
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)
            Link(L10n.string("服務條款"), destination: AppURLs.terms)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)
            Spacer()
        }
    }

    // MARK: - Computed Properties

    /// 目前 Pro entitlement 快照 + App Store 價格 — 餵給純 `SubscriptionPaywallCopy`。
    /// 所有文案邏輯收斂到該 enum（可單元測試），此處僅為 view-binding 薄轉發。
    private var pro: KGSubscriptionStatus { subscriptionManager.entitlements.pro }
    private var productPrice: String? { subscriptionManager.proProduct?.displayPrice }

    private var isCancelledButActive: Bool { pro.isCancelledButActive }
    private var isAdminGranted: Bool { SubscriptionPaywallCopy.isAdminGranted(pro) }

    private var activeSummaryText: String { SubscriptionPaywallCopy.activeSummary(pro) }
    private var paywallSummaryText: String { SubscriptionPaywallCopy.marketingSummary }
    private var billedAmountLine: String { SubscriptionPaywallCopy.billedAmount(pro, productDisplayPrice: productPrice) }
    private var trialInfoLine: String? { SubscriptionPaywallCopy.trialInfo(pro) }
    private var priceLine: String { SubscriptionPaywallCopy.priceLine(pro, productDisplayPrice: productPrice) }
    private var ctaButtonTitle: String { SubscriptionPaywallCopy.ctaButtonTitle(pro, productDisplayPrice: productPrice) }
    private var entitlementSourceLine: String { SubscriptionPaywallCopy.entitlementSource(pro) }
    private var primaryActionTitle: String { SubscriptionPaywallCopy.primaryActionTitle(pro) }
    private var footerNote: String { SubscriptionPaywallCopy.footerNote(pro) }
}
