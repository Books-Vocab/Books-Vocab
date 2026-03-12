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
                    badgeText: SubscriptionPresentation.badgeText(for: pro),
                    badgeTone: SubscriptionPresentation.badgeTone(for: pro),
                    summary: SubscriptionPresentation.summary(for: pro),
                    detail: SubscriptionPresentation.detail(for: pro, proProduct: subscriptionManager.proProduct),
                    sourceLabel: SubscriptionPresentation.sourceLabel(for: pro),
                    managementNote: SubscriptionPresentation.managementNote(for: pro),
                    pricingUnavailableMessage: SubscriptionPresentation.pricingUnavailableMessage(for: pro, hasStorePrice: subscriptionManager.proProduct?.displayPrice.isEmpty == false),
                    restoreLabel: SubscriptionPresentation.restoreLabel(for: pro),
                    restoreDescription: SubscriptionPresentation.restoreDescription(for: pro),
                    isRestoreAvailable: SubscriptionPresentation.restoreAvailable(for: pro),
                    ctaTitle: SubscriptionPresentation.ctaTitle(for: pro),
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

}

#Preview {
    SettingsView()
}
