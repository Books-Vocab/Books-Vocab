//
//  SettingsView.swift
//  BooksBrowser
//

import SwiftUI
import SwiftData
import StoreKit

struct SettingsView: View {
    @Environment(\.dismiss) var dismiss
    @Environment(\.modelContext) var modelContext
    @Environment(\.kgService) var kgService
    @Environment(\.authManager) var authManager
    @Environment(\.subscriptionManager) var subscriptionManager
    @Environment(\.openURL) var openURL
    @Environment(\.requestReview) var requestReview
    @Environment(\.toastCoordinator) var toastCoordinator
    @EnvironmentObject var appLanguage: AppLanguageStore
    @EnvironmentObject var appearanceStore: AppAppearanceStore
    @Environment(\.reviewSettingsStore) var reviewSettingsStore
    @Environment(\.autoSyncSettingsStore) var autoSyncSettingsStore
    @State var coordinator = SettingsCoordinator()
    @State var exportURL: URL?
    /// Predicate 對應 shouldAppearInKnowledgeList — 僅用於 displayCardCount
    @Query(filter: #Predicate<VocabularyEntry> {
        $0.syncStatus == 1 &&
        $0.actionType != "delete" &&
        $0.isArchived == false
    }) var allEntries: [VocabularyEntry]

    var body: some View {
        SettingsPresenter(
            state: presenterState,
            translationSourceLang: translationSourceLangBinding,
            translationTargetLang: translationTargetLangBinding,
            onTranslationLanguageChanged: { source, target in
                await coordinator.updateTranslationLanguage(
                    source: source,
                    target: target,
                    authManager: authManager,
                    kgService: kgService,
                    toastCoordinator: toastCoordinator
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
        .onChange(of: coordinator.showSubscriptionPaywall) { _, isPresented in
            if !isPresented, authManager.isLoggedIn {
                Task {
                    await subscriptionManager.refresh(using: kgService, authManager: authManager, force: true)
                }
            }
        }
        .onAppear {
            coordinator.handleAppear()
        }
        .toastSheet(isPresented: $coordinator.showSubscriptionPaywall) {
            SubscriptionPaywallSheet()
        }
        .toastSheet(item: $exportURL) { url in
            PlatformShareView(url: url)
        }
        .toastSheet(isPresented: $coordinator.showDeleteAccountConfirm) {
            SettingsDeleteAccountSheet(
                onConfirm: {
                    Task {
                        await coordinator.deleteAccount(
                            authManager: authManager,
                            kgService: kgService,
                            modelContext: modelContext
                        )
                    }
                },
                isDeleting: coordinator.isDeletingAccount
            )
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
