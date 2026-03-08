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
        SettingsPresenterState(
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
                    lastSyncDescription: kgService.lastSyncDate?.formatted(.relative(presentation: .named))
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
            showMochiInfo: coordinator.presentMochiInfo,
            requestDeleteAccount: coordinator.requestDeleteAccount
        )
    }

    var body: some View {
        SettingsPresenter(
            state: presenterState,
            mochiApiKey: mochiApiKeyBinding,
            manualLoginUserId: manualLoginBinding,
            actions: presenterActions
        )
        .task(id: authManager.isLoggedIn) {
            await coordinator.loadData(authManager: authManager, kgService: kgService)
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
}

#Preview {
    SettingsView()
}
