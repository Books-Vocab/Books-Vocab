import SwiftUI

struct SubscriptionPaywallSheet: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss
    @Environment(\.subscriptionManager) private var subscriptionManager
    @Environment(\.authManager) private var authManager
    @Environment(\.kgService) private var kgService

    var body: some View {
        NavigationStack {
            ScrollView {
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

                    VStack(alignment: .leading, spacing: vocabSkin.spacing.microGap) {
                        Text(priceLine)
                            .font(vocabSkin.typography.sectionTitle)
                            .foregroundStyle(vocabSkin.palette.primaryText)
                        Text(L10n.format("權限來源：%@", entitlementSourceLine))
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    }

                    accessStateCard

                    VStack(alignment: .leading, spacing: vocabSkin.spacing.rowContentSpacing) {
                        paywallFeatureRow("AI 翻譯與語境解釋")
                        paywallFeatureRow("知識庫同步與跨裝置狀態")
                        paywallFeatureRow("關聯圖與內建複習")
                    }
                    .padding(vocabSkin.spacing.cardPadding)
                    .background(vocabSkin.palette.cardBackground)
                    .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                            .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                    )

                    VStack(spacing: vocabSkin.spacing.controlGap) {
                        Button {
                            Task {
                                if isAdminGranted {
                                    await subscriptionManager.refresh(using: kgService, authManager: authManager)
                                } else if subscriptionManager.hasProAccess {
                                    await subscriptionManager.refresh(using: kgService, authManager: authManager)
                                } else {
                                    await subscriptionManager.purchasePro(using: kgService, authManager: authManager)
                                }
                            }
                        } label: {
                            HStack {
                                if subscriptionManager.isLoading {
                                    ProgressView()
                                        .controlSize(.small)
                                }
                                Text(primaryActionTitle)
                                Spacer()
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.vocabAction(.primary))
                        .disabled(subscriptionManager.isLoading)

                        if !isAdminGranted {
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
                        } else {
                            VocabStateMessageCard(
                                title: "恢復購買不適用",
                                systemImage: "person.badge.key",
                                description: "目前 Pro 來自管理員授權，不透過訂閱管理。如需調整，請聯絡管理員。"
                            )
                        }
                    }

                    if let purchaseStatusMessage = subscriptionManager.purchaseStatusMessage {
                        VocabStateMessageCard(
                            title: purchaseStatusMessage,
                            systemImage: "checkmark.circle"
                        )
                    }

                    if let lastError = subscriptionManager.lastError, !lastError.isEmpty {
                        VocabStateMessageCard(
                            title: "App Store 載入失敗",
                            systemImage: "exclamationmark.triangle.fill",
                            description: lastError
                        ) {
                            Text(L10n.format("目前商品 ID：%@", subscriptionManager.proProductIdentifier))
                                .font(vocabSkin.typography.monoLabel)
                                .foregroundStyle(vocabSkin.palette.tertiaryText)
                                .textSelection(.enabled)
                        }
                    }

                    Text(footerNote)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }
                .padding(vocabSkin.spacing.sheetPaddingCompact)
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
        }
    }

    private var paywallSummaryText: String {
        if isAdminGranted {
            return L10n.string("目前帳號已啟用 Pro 功能。如需調整或查看有效期，請聯絡管理員。")
        }
        if subscriptionManager.hasProAccess {
            return L10n.string("目前帳號已具備 Pro 權限。若狀態顯示不一致，可重新同步或恢復購買。")
        }
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
        if let lastError = subscriptionManager.lastError, !lastError.isEmpty {
            return L10n.string("無法載入 App Store 價格")
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
        if subscriptionManager.hasProAccess {
            return L10n.string("重新同步訂閱狀態")
        }
        return L10n.string("開始免費試用")
    }

    private var footerNote: String {
        if isAdminGranted {
            return L10n.string("此帳號目前由管理員授權為 Pro；若需延長、撤銷或調整，請聯絡管理員。")
        }
        return L10n.string("價格與免費試用長度會以 App Store 與你的地區顯示為準。")
    }

    private var accessStateCard: some View {
        Group {
            if isAdminGranted {
                VocabStateMessageCard(
                    title: "管理員授權中",
                    systemImage: "person.badge.key.fill",
                    description: "這裡主要提供狀態查看與重新整理。如需調整，請聯絡管理員。"
                )
            } else if subscriptionManager.entitlements.pro.is_trial {
                VocabStateMessageCard(
                    title: "免費試用中",
                    systemImage: "timer",
                    description: "試用到期前可完整使用 Reader AI、同步、關聯圖與複習功能。"
                )
            } else if subscriptionManager.hasProAccess {
                VocabStateMessageCard(
                    title: "訂閱已啟用",
                    systemImage: "checkmark.circle.fill",
                    description: "若不同裝置顯示不一致，可重新同步訂閱狀態或恢復購買。"
                )
            } else {
                VocabStateMessageCard(
                    title: "尚未啟用 Pro",
                    systemImage: "sparkles.rectangle.stack",
                    description: "價格、免費試用與續訂規則都會以 App Store 實際顯示為準。"
                )
            }
        }
    }

    private func paywallFeatureRow(_ text: String) -> some View {
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
}
