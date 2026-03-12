//
//  SettingsView.swift
//  BooksBrowser
//

import SwiftUI
import StoreKit

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.subscriptionManager) private var subscriptionManager
    @Environment(\.openURL) private var openURL
    @Environment(\.requestReview) private var requestReview
    @EnvironmentObject private var appLanguage: AppLanguageStore
    @EnvironmentObject private var appearanceStore: AppAppearanceStore
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore
    @State private var showSubscriptionPaywall = false
    @State private var coordinator = SettingsCoordinator()

    private var userInitials: String? {
        guard let name = authManager.displayName, !name.isEmpty else { return nil }
        let parts = name.split(separator: " ")
        if parts.count >= 2 {
            return String(parts[0].prefix(1)) + String(parts[1].prefix(1))
        }
        return String(name.prefix(2)).uppercased()
    }

    private var authDebugState: SettingsPresenterState.DebugAuthSection? {
#if DEBUG
        SettingsPresenterState.DebugAuthSection(manualLoginHint: L10n.string("手動登入只用於切換測試帳號；Pro 權限請改由 /admin 或 App Store 管理。"))
#else
        nil
#endif
    }

    private var syncSummaryText: String {
        if !kgService.isConnected { return "離線".localized }
        var parts: [String] = ["已連線".localized]
        if kgService.serverCardCount > 0 {
            parts.append(L10n.format("%@ 張", "\(kgService.serverCardCount)"))
        }
        if let lastSync = kgService.lastSyncDate?.formatted(.relative(presentation: .named)) {
            parts.append(lastSync)
        }
        return parts.joined(separator: " · ")
    }

    private var presenterState: SettingsPresenterState {
        let pro = subscriptionManager.entitlements.pro
        return SettingsPresenterState(
            auth: .init(
                isLoggedIn: authManager.isLoggedIn,
                userInitials: userInitials,
                avatarURL: authManager.avatarURL,
                displayName: authManager.displayName ?? authManager.userEmail ?? L10n.string("已登入"),
                email: authManager.displayName != nil ? authManager.userEmail : nil,
                authError: authManager.authError,
                isAuthenticating: authManager.isAuthenticating,
                iconBreathing: coordinator.iconBreathing,
                debug: authDebugState
            ),
            preferences: .init(
                selectedLanguage: L10n.string(appLanguage.selection.titleKey),
                selectedAppearance: appearanceStore.selection.titleKey,
                translationSource: coordinator.translationSourceLang.nativeName,
                translationTarget: coordinator.translationTargetLang.nativeName,
                selectedReviewMode: reviewSettingsStore.settings.mode.displayName
            ),
            kg: authManager.isLoggedIn
                ? .init(
                    serverURL: KGService.getServerURL(),
                    isConnected: kgService.isConnected,
                    connectionPulse: coordinator.connectionPulse,
                    serverCardCount: kgService.serverCardCount,
                    lastSyncDescription: kgService.lastSyncDate?.formatted(.relative(presentation: .named)),
                    debug: kgDebugState
                )
                : nil,
            subscription: authManager.isLoggedIn
                ? .init(
                    isActive: pro.is_active,
                    planName: pro.plan_name ?? "Books & Vocab Pro",
                    badgeText: subscriptionBadgeText(for: pro),
                    badgeTone: subscriptionBadgeTone(for: pro),
                    summary: subscriptionSummary(for: pro),
                    detail: subscriptionDetail(for: pro),
                    sourceLabel: subscriptionSourceLabel(for: pro),
                    managementNote: subscriptionManagementNote(for: pro),
                    pricingUnavailableMessage: subscriptionPricingUnavailableMessage(for: pro),
                    restoreLabel: restoreLabel(for: pro),
                    restoreDescription: restoreDescription(for: pro),
                    isRestoreAvailable: restoreAvailable(for: pro),
                    ctaTitle: subscriptionCTA(for: pro),
                    isRefreshing: subscriptionManager.isLoading
                )
                : nil,
            syncSummary: authManager.isLoggedIn
                ? .init(
                    isConnected: kgService.isConnected,
                    summaryText: syncSummaryText
                )
                : nil,
            optionalIntegration: authManager.isLoggedIn ? .init(isEnabled: true) : nil,
            about: .init(
                version: "1.1.0",
                developerName: "陳亮宇"
            ),
            danger: authManager.isLoggedIn ? .init(isDeletingAccount: coordinator.isDeletingAccount) : nil
        )
    }

    private var presenterActions: SettingsPresenterActions {
        SettingsPresenterActions(
            dismiss: { dismiss() },
            loginWithGoogle: { authManager.loginWithGoogle(modelContainer: modelContext.container) },
            loginWithApple: { authManager.loginWithApple(modelContainer: modelContext.container) },
            logout: { authManager.logout(modelContainer: modelContext.container, reason: "settings_logout") },
            manualLogin: { coordinator.handleManualLogin(authManager: authManager) },
            useProductionBackend: {
                #if DEBUG
                Task {
                    await coordinator.useProductionBackend(authManager: authManager, kgService: kgService)
                }
                #endif
            },
            useLocalBackend: {
                #if DEBUG
                Task {
                    await coordinator.useLocalBackend(authManager: authManager, kgService: kgService)
                }
                #endif
            },
            selectLanguage: { appLanguage.setLanguage($0) },
            selectAppearance: { appearanceStore.setAppearance($0) },
            showSubscriptionPaywall: {
                subscriptionManager.activePaywallSource = .settings
                showSubscriptionPaywall = true
            },
            showOptionalIntegrationInfo: coordinator.presentOptionalIntegrationInfo,
            requestDeleteAccount: coordinator.requestDeleteAccount,
            openPrivacyPolicy: {
                if let url = URL(string: "https://wordnexus.lol/privacy.html") {
                    openURL(url)
                }
            },
            openTermsOfService: {
                if let url = URL(string: "https://wordnexus.lol/terms.html") {
                    openURL(url)
                }
            },
            openSupport: {
                if let url = URL(string: "https://wordnexus.lol/support.html") {
                    openURL(url)
                }
            },
            requestAppRating: {
                requestReview()
            }
        )
    }

    var body: some View {
        SettingsPresenter(
            state: presenterState,
            optionalIntegrationApiKey: optionalIntegrationApiKeyBinding,
            translationSourceLang: translationSourceLangBinding,
            translationTargetLang: translationTargetLangBinding,
            onTranslationLanguageChanged: { source, target in
                coordinator.updateTranslationLanguage(
                    source: source,
                    target: target,
                    authManager: authManager,
                    kgService: kgService
                )
            },
            manualLoginUserId: manualLoginBinding,
            debugLocalServerURL: debugLocalServerURLBinding,
            actions: presenterActions
        )
        .task(id: authManager.isLoggedIn) {
            await coordinator.loadData(authManager: authManager, kgService: kgService)
            if authManager.isLoggedIn {
                await subscriptionManager.loadProducts()
                await subscriptionManager.refresh(using: kgService, authManager: authManager, force: false)
            } else {
                // 登出時立即清除訂閱狀態
                await subscriptionManager.refresh(using: kgService, authManager: authManager, force: true)
            }
        }
        .onChange(of: showSubscriptionPaywall) { _, isPresented in
            if !isPresented, authManager.isLoggedIn {
                Task {
                    await subscriptionManager.refresh(using: kgService, authManager: authManager, force: true)
                }
            }
        }
        .onChange(of: coordinator.optionalIntegrationApiKey) { _, _ in
            coordinator.scheduleOptionalIntegrationSave(authManager: authManager, kgService: kgService)
        }
        .onAppear {
            coordinator.handleAppear()
        }
        .sheet(isPresented: $coordinator.showOptionalIntegrationInfo) {
            OptionalIntegrationInfoSheetView()
        }
        .sheet(isPresented: $showSubscriptionPaywall) {
            SubscriptionPaywallSheet()
        }
        .alert("刪除帳號與雲端資料？".localized, isPresented: $coordinator.showDeleteAccountConfirm) {
            Button("取消".localized, role: .cancel) {}
            Button("確認刪除".localized, role: .destructive) {
                Task {
                    await coordinator.deleteAccount(
                        authManager: authManager,
                        kgService: kgService,
                        modelContext: modelContext
                    )
                }
            }
        } message: {
            Text("此操作會永久刪除帳號、雲端生詞資料與同步設定，且無法復原。".localized)
        }
        .alert("刪除失敗".localized, isPresented: Binding(
            get: { coordinator.deleteAccountError != nil },
            set: { if !$0 { coordinator.clearDeleteAccountError() } }
        )) {
            Button("好".localized, action: coordinator.clearDeleteAccountError)
        } message: {
            Text((coordinator.deleteAccountError ?? "請稍後再試").localized)
        }
    }

    private var translationSourceLangBinding: Binding<TranslationLanguage> {
        Binding(
            get: { coordinator.translationSourceLang },
            set: { coordinator.translationSourceLang = $0 }
        )
    }

    private var translationTargetLangBinding: Binding<TranslationLanguage> {
        Binding(
            get: { coordinator.translationTargetLang },
            set: { coordinator.translationTargetLang = $0 }
        )
    }

    private var optionalIntegrationApiKeyBinding: Binding<String> {
        Binding(
            get: { coordinator.optionalIntegrationApiKey },
            set: { coordinator.optionalIntegrationApiKey = $0 }
        )
    }

    private var manualLoginBinding: Binding<String>? {
#if DEBUG
        Binding(
            get: { coordinator.manualLoginUserId },
            set: { coordinator.manualLoginUserId = $0 }
        )
#else
        nil
#endif
    }

    private var debugLocalServerURLBinding: Binding<String>? {
#if DEBUG
        Binding(
            get: { coordinator.debugLocalServerURL },
            set: { coordinator.debugLocalServerURL = $0 }
        )
#else
        nil
#endif
    }

    private var kgDebugState: SettingsPresenterState.KGSection.DebugSection? {
#if DEBUG
        .init(
            isUsingLocalServer: KGService.getDebugServerMode() == .local,
            localServerURL: coordinator.debugLocalServerURL
        )
#else
        nil
#endif
    }

    private func subscriptionBadgeText(for status: KGSubscriptionStatus) -> String {
        if status.source == "admin", status.is_active {
            return "ADMIN"
        }
        if status.isCancelledButActive {
            return "EXPIRING"
        }
        switch status.status {
        case "active":
            return "ACTIVE"
        case "trial":
            return "TRIAL"
        case "grace_period":
            return "GRACE"
        default:
            return "FREE"
        }
    }

    private func subscriptionBadgeTone(for status: KGSubscriptionStatus) -> SubscriptionBadgeTone {
        if status.source == "admin", status.is_active {
            return .success
        }
        if status.isCancelledButActive {
            return .accent
        }
        switch status.status {
        case "active":
            return .success
        case "trial", "grace_period":
            return .accent
        default:
            return .neutral
        }
    }

    private func subscriptionSummary(for status: KGSubscriptionStatus) -> String {
        if status.source == "admin", status.is_active {
            return L10n.string("你目前已由管理員授權為 Pro，可使用 AI 翻譯、雲端同步、知識圖譜與內建複習。")
        }
        if status.isCancelledButActive {
            return L10n.format("訂閱已取消，將於 %@ 到期。到期前仍可使用所有 Pro 功能。", status.formattedExpiryDate)
        }
        if status.status == "grace_period" {
            return L10n.string("訂閱目前在寬限期，請確認付款方式以維持存取。")
        }
        if status.is_trial {
            return L10n.string("免費試用中，期間可使用 AI 翻譯、雲端同步、知識圖譜與內建複習。")
        }
        if status.is_active {
            return L10n.string("你目前已解鎖 AI 翻譯、雲端同步、知識圖譜與第三方整合。")
        }
        return L10n.string("升級後可使用 AI 翻譯、語境解釋、雲端同步、知識圖譜與內建複習。")
    }

    private func subscriptionDetail(for status: KGSubscriptionStatus) -> String {
        if status.source == "admin", status.is_active {
            if let expiresAt = status.expires_at, !expiresAt.isEmpty {
                return L10n.format("來源：管理員授權 · 有效至 %@", expiresAt)
            }
            return L10n.string("來源：管理員授權")
        }
        if let price = subscriptionManager.proProduct?.displayPrice, !price.isEmpty, !status.is_active {
            let days = status.trial_days ?? 7
            return L10n.format("%@ / month · %@ 天免費試用", price, "\(days)")
        }
        if let price = status.price_display, !price.isEmpty {
            if let expiresAt = status.expires_at, !expiresAt.isEmpty {
                return L10n.format("%@ · 到期 %@", price, expiresAt)
            }
            return price
        }
        if let days = status.trial_days, !status.is_active {
            return L10n.format("預設提供 %@ 天免費試用", "\(days)")
        }
        return L10n.string("價格與試用長度會以 App Store 顯示為準")
    }

    private func subscriptionCTA(for status: KGSubscriptionStatus) -> String {
        if status.source == "admin", status.is_active {
            return L10n.string("查看權限")
        }
        return status.is_active ? L10n.string("管理訂閱") : L10n.string("開始免費試用")
    }

    private func subscriptionSourceLabel(for status: KGSubscriptionStatus) -> String {
        if status.source == "admin", status.is_active {
            return L10n.string("管理員授權")
        }
        return L10n.string("App Store 訂閱")
    }

    private func subscriptionManagementNote(for status: KGSubscriptionStatus) -> String {
        if status.source == "admin", status.is_active {
            return L10n.string("如需延長或調整，請聯絡管理員。")
        }
        if status.is_active {
            return L10n.string("可在訂閱頁重新同步或恢復購買，確認訂閱狀態。")
        }
        return L10n.string("價格、免費試用與續訂都以 App Store 顯示為準。")
    }

    private func subscriptionPricingUnavailableMessage(for status: KGSubscriptionStatus) -> String? {
        if status.source == "admin", status.is_active {
            return nil
        }
        let hasStorePrice = subscriptionManager.proProduct?.displayPrice.isEmpty == false
        let hasRemotePrice = status.price_display?.isEmpty == false
        guard !hasStorePrice, !hasRemotePrice else { return nil }

        return L10n.string("App Store 價格載入中，稍後會自動更新。")
    }

    private func restoreLabel(for status: KGSubscriptionStatus) -> String {
        if status.source == "admin", status.is_active {
            return L10n.string("恢復購買不可用")
        }
        return L10n.string("可恢復購買")
    }

    private func restoreDescription(for status: KGSubscriptionStatus) -> String {
        if status.source == "admin", status.is_active {
            return L10n.string("這個帳號的 Pro 來自管理員授權；若需延長或撤銷，請由管理員處理。")
        }
        if status.is_active {
            return L10n.string("若裝置間狀態不同，可在訂閱頁使用恢復購買重新對齊 App Store。")
        }
        return L10n.string("若先前已訂閱但此處顯示未啟用，可在訂閱頁使用恢復購買。")
    }

    private func restoreAvailable(for status: KGSubscriptionStatus) -> Bool {
        !(status.source == "admin" && status.is_active)
    }

}

#Preview {
    SettingsView()
}
