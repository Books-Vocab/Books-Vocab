//
//  SettingsView.swift
//  BooksBrowser
//

import SwiftUI
import StoreKit

struct SettingsView: View {
    @Environment(\.dismiss) var dismiss
    @Environment(\.modelContext) var modelContext
    @Environment(\.kgService) var kgService
    @Environment(\.authManager) var authManager
    @Environment(\.subscriptionManager) var subscriptionManager
    @Environment(\.openURL) var openURL
    @Environment(\.requestReview) var requestReview
    @EnvironmentObject var appLanguage: AppLanguageStore
    @EnvironmentObject var appearanceStore: AppAppearanceStore
    @Environment(\.reviewSettingsStore) var reviewSettingsStore
    @State var showSubscriptionPaywall = false
    @State var coordinator = SettingsCoordinator()

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
}

#Preview {
    SettingsView()
}
