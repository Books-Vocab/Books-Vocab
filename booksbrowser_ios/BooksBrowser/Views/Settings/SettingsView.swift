//
//  SettingsView.swift
//  BooksBrowser
//

import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.subscriptionManager) private var subscriptionManager
    @State private var showSubscriptionPaywall = false
    @StateObject private var coordinator = SettingsCoordinator()

    private var userInitials: String? {
        guard let name = authManager.displayName, !name.isEmpty else { return nil }
        let parts = name.split(separator: " ")
        if parts.count >= 2 {
            return String(parts[0].prefix(1)) + String(parts[1].prefix(1))
        }
        return String(name.prefix(2)).uppercased()
    }

#if DEBUG
    private var isCurrentAccountDeveloper: Bool {
        guard let userId = authManager.userId else { return false }
        return !coordinator.developerAccountId.isEmpty && coordinator.developerAccountId == userId
    }
#endif

    private var authDebugState: SettingsPresenterState.DebugAuthSection? {
#if DEBUG
        SettingsPresenterState.DebugAuthSection(developerAccountId: coordinator.developerAccountId)
#else
        nil
#endif
    }

    private var authIsDeveloper: Bool {
#if DEBUG
        isCurrentAccountDeveloper
#else
        false
#endif
    }

    private var aboutDeveloperAccountId: String? {
#if DEBUG
        coordinator.developerAccountId
#else
        nil
#endif
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
                iconBreathing: coordinator.iconBreathing,
                isDeveloper: authIsDeveloper,
                debug: authDebugState
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
                    planName: pro.plan_name ?? "BooksBrowser Pro",
                    badgeText: subscriptionBadgeText(for: pro),
                    badgeTone: subscriptionBadgeTone(for: pro),
                    summary: subscriptionSummary(for: pro),
                    detail: subscriptionDetail(for: pro),
                    ctaTitle: pro.is_active ? "管理訂閱" : "開始免費試用",
                    isRefreshing: subscriptionManager.isLoading
                )
                : nil,
            mochi: authManager.isLoggedIn ? .init(isEnabled: true) : nil,
            about: .init(
                version: "1.1.0",
                developerName: "陳亮宇",
                developerAccountId: aboutDeveloperAccountId
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
            setDeveloperAccount: coordinator.setDeveloperAccount,
            clearDeveloperAccount: coordinator.clearDeveloperAccount,
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
            showSubscriptionPaywall: {
                subscriptionManager.activePaywallSource = .settings
                showSubscriptionPaywall = true
            },
            showMochiInfo: coordinator.presentMochiInfo,
            requestDeleteAccount: coordinator.requestDeleteAccount
        )
    }

    var body: some View {
        SettingsPresenter(
            state: presenterState,
            mochiApiKey: mochiApiKeyBinding,
            manualLoginUserId: manualLoginBinding,
            debugLocalServerURL: debugLocalServerURLBinding,
            actions: presenterActions
        )
        .task(id: authManager.isLoggedIn) {
            await coordinator.loadData(authManager: authManager, kgService: kgService)
            if authManager.isLoggedIn {
                await subscriptionManager.loadProducts()
                await subscriptionManager.refresh(using: kgService, authManager: authManager)
            }
        }
        .onChange(of: coordinator.mochiApiKey) { _, _ in
            coordinator.scheduleMochiSave(authManager: authManager, kgService: kgService)
        }
        .onAppear {
            coordinator.handleAppear()
        }
        .sheet(isPresented: $coordinator.showMochiInfo) {
            MochiInfoSheetView()
        }
        .sheet(isPresented: $showSubscriptionPaywall) {
            SubscriptionPaywallSheet()
        }
        .alert("刪除帳號與雲端資料？", isPresented: $coordinator.showDeleteAccountConfirm) {
            Button("取消", role: .cancel) {}
            Button("確認刪除", role: .destructive) {
                Task {
                    await coordinator.deleteAccount(
                        authManager: authManager,
                        kgService: kgService,
                        modelContext: modelContext
                    )
                }
            }
        } message: {
            Text("此操作會永久刪除帳號、雲端生詞資料與同步設定，且無法復原。")
        }
        .alert("刪除失敗", isPresented: Binding(
            get: { coordinator.deleteAccountError != nil },
            set: { if !$0 { coordinator.clearDeleteAccountError() } }
        )) {
            Button("好", action: coordinator.clearDeleteAccountError)
        } message: {
            Text((coordinator.deleteAccountError ?? "請稍後再試").localized)
        }
    }

    private var mochiApiKeyBinding: Binding<String> {
        Binding(
            get: { coordinator.mochiApiKey },
            set: { coordinator.mochiApiKey = $0 }
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
        switch status.status {
        case "active":
            return .success
        case "trial":
            return .accent
        default:
            return .neutral
        }
    }

    private func subscriptionSummary(for status: KGSubscriptionStatus) -> String {
        if status.is_trial {
            return "免費試用中，期間可使用 AI 翻譯、雲端同步、知識圖譜與 Mochi 同步。"
        }
        if status.is_active {
            return "你目前已解鎖 AI 翻譯、雲端同步、知識圖譜與第三方整合。"
        }
        return "升級後可使用 AI 翻譯、語境解釋、雲端同步、知識圖譜與 Mochi 同步。"
    }

    private func subscriptionDetail(for status: KGSubscriptionStatus) -> String {
        if let price = subscriptionManager.proProduct?.displayPrice, !price.isEmpty, !status.is_active {
            let days = status.trial_days ?? 7
            return "\(price) / month · \(days) 天免費試用"
        }
        if let price = status.price_display, !price.isEmpty {
            if let expiresAt = status.expires_at, !expiresAt.isEmpty {
                return "\(price) · 到期 \(expiresAt)"
            }
            return price
        }
        if let days = status.trial_days, !status.is_active {
            return "預設提供 \(days) 天免費試用"
        }
        return "價格與試用長度會以 App Store 顯示為準"
    }
}

#Preview {
    SettingsView()
}
