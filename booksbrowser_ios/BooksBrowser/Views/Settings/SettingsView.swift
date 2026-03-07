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

#if DEBUG
    @AppStorage("developer_account_id") private var developerAccountId: String = ""
    @State private var manualLoginUserId: String = ""
#endif
    @State private var mochiApiKey: String = ""
    @State private var fetchedKey: String = ""
    @State private var saveTask: Task<Void, Never>? = nil
    @State private var showMochiInfo = false
    @State private var connectionPulse = false
    @State private var iconBreathing = false
    @State private var showDeleteAccountConfirm = false
    @State private var isDeletingAccount = false
    @State private var deleteAccountError: String?
    @State private var showSubscriptionPaywall = false

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
        return !developerAccountId.isEmpty && developerAccountId == userId
    }
#endif

    private var authDebugState: SettingsPresenterState.DebugAuthSection? {
#if DEBUG
        SettingsPresenterState.DebugAuthSection(developerAccountId: developerAccountId)
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
        developerAccountId
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
                displayName: authManager.displayName ?? authManager.userEmail ?? "已登入",
                email: authManager.displayName != nil ? authManager.userEmail : nil,
                authError: authManager.authError,
                iconBreathing: iconBreathing,
                isDeveloper: authIsDeveloper,
                debug: authDebugState
            ),
            kg: authManager.isLoggedIn
                ? .init(
                    serverURL: KGService.getServerURL(),
                    isConnected: kgService.isConnected,
                    connectionPulse: connectionPulse,
                    serverCardCount: kgService.serverCardCount,
                    lastSyncDescription: kgService.lastSyncDate?.formatted(.relative(presentation: .named))
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
            danger: authManager.isLoggedIn ? .init(isDeletingAccount: isDeletingAccount) : nil
        )
    }

    private var presenterActions: SettingsPresenterActions {
        SettingsPresenterActions(
            dismiss: { dismiss() },
            loginWithGoogle: { authManager.loginWithGoogle(modelContainer: modelContext.container) },
            logout: { authManager.logout(modelContainer: modelContext.container, reason: "settings_logout") },
            manualLogin: handleManualLogin,
            setDeveloperAccount: setDeveloperAccount,
            clearDeveloperAccount: clearDeveloperAccount,
            showSubscriptionPaywall: {
                subscriptionManager.activePaywallSource = .settings
                showSubscriptionPaywall = true
            },
            showMochiInfo: { showMochiInfo = true },
            requestDeleteAccount: { showDeleteAccountConfirm = true }
        )
    }

    var body: some View {
        SettingsPresenter(
            state: presenterState,
            mochiApiKey: $mochiApiKey,
            manualLoginUserId: manualLoginBinding,
            actions: presenterActions
        )
        .task(id: authManager.isLoggedIn) {
            await kgService.healthCheck()
            connectionPulse.toggle()

            if authManager.isLoggedIn {
                await subscriptionManager.loadProducts()
                await subscriptionManager.refresh(using: kgService, authManager: authManager)
                if let config = try? await kgService.fetchUserConfig() {
                    let fetched = config.mochi_api_key ?? ""
                    fetchedKey = fetched
                    mochiApiKey = fetched
                }
            } else {
                fetchedKey = ""
                mochiApiKey = ""
            }
        }
        .onChange(of: mochiApiKey) {
            guard mochiApiKey != fetchedKey else { return }
            saveTask?.cancel()
            saveTask = Task {
                try? await Task.sleep(for: .milliseconds(600))
                guard !Task.isCancelled else { return }
                if authManager.isLoggedIn {
                    _ = try? await kgService.updateUserConfig(mochiKey: mochiApiKey.isEmpty ? nil : mochiApiKey)
                    fetchedKey = mochiApiKey
                }
            }
        }
        .onAppear {
            iconBreathing = true
#if DEBUG
            manualLoginUserId = developerAccountId
#endif
        }
        .sheet(isPresented: $showMochiInfo) {
            MochiInfoSheetView()
        }
        .sheet(isPresented: $showSubscriptionPaywall) {
            SubscriptionPaywallSheet()
        }
        .alert("刪除帳號與雲端資料？", isPresented: $showDeleteAccountConfirm) {
            Button("取消", role: .cancel) {}
            Button("確認刪除", role: .destructive) {
                Task { await deleteAccount() }
            }
        } message: {
            Text("此操作會永久刪除帳號、雲端生詞資料與同步設定，且無法復原。")
        }
        .alert("刪除失敗", isPresented: Binding(
            get: { deleteAccountError != nil },
            set: { if !$0 { deleteAccountError = nil } }
        )) {
            Button("好") { deleteAccountError = nil }
        } message: {
            Text(deleteAccountError ?? "請稍後再試")
        }
    }

    @MainActor
    private func deleteAccount() async {
        guard authManager.isLoggedIn, !isDeletingAccount else { return }
        isDeletingAccount = true
        defer { isDeletingAccount = false }

        do {
            try await kgService.deleteAccount()
            authManager.logout(modelContainer: modelContext.container, reason: "delete_account")
        } catch {
            deleteAccountError = "無法刪除帳號：\(error.localizedDescription)"
        }
    }

    private var manualLoginBinding: Binding<String>? {
#if DEBUG
        $manualLoginUserId
#else
        nil
#endif
    }

    private func handleManualLogin() {
#if DEBUG
        let id = manualLoginUserId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty else { return }
        authManager.login(customToken: id)
#endif
    }

    private func setDeveloperAccount() {
#if DEBUG
        developerAccountId = manualLoginUserId.trimmingCharacters(in: .whitespacesAndNewlines)
#endif
    }

    private func clearDeveloperAccount() {
#if DEBUG
        developerAccountId = ""
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
