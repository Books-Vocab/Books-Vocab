//
//  SettingsView.swift
//  Books & Vocab
//

import SwiftUI
import SwiftData
import StoreKit

struct SettingsView: View {
    @ObserveInjection private var inject
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
    @Environment(\.autoLinkSettingsStore) var autoLinkSettingsStore
    @Environment(\.feedbackSettingsStore) var feedbackSettingsStore
    @State var coordinator = SettingsCoordinator()
    @State var exportURL: URL?
    /// Predicate 對應 shouldAppearInKnowledgeList — 僅用於 displayCardCount
    @Query(filter: #Predicate<VocabularyEntry> {
        $0.syncStatus == 1 &&
        $0.actionType != "delete" &&
        $0.isArchived == false
    }) var allEntries: [VocabularyEntry]

    var body: some View {
#if DEBUG
        let _ = RenderStormProbe.shared.tick("SettingsView")
        let _ = RenderStormProbe.printChangesEnabled ? Self._printChanges() : ()
#endif
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
            onPauseReviewClockChanged: { isPaused in
                await coordinator.updateReviewClock(
                    isPaused: isPaused,
                    reviewSettingsStore: reviewSettingsStore,
                    authManager: authManager,
                    kgService: kgService,
                    toastCoordinator: toastCoordinator
                )
            },
            onReviewModeChanged: { newSettings in
                await coordinator.updateReviewMode(
                    newSettings,
                    reviewSettingsStore: reviewSettingsStore,
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
        .subscriptionPaywallSheet(isPresented: $coordinator.showSubscriptionPaywall)
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
            Text(coordinator.deleteAccountError ?? "請稍後再試".localized)
        }
        .enableInjection()
    }
}

extension View {
    /// 呈現 SettingsView，並在 sheet 邊界 re-inject 它依賴的兩個 app 級
    /// ObservableObject。SwiftUI `.sheet` 會傳遞 value-based `.environment(\.key)`，
    /// 但【不】跨 sheet 邊界傳遞 `@EnvironmentObject` —— 少了這層，SettingsView
    /// 讀 appLanguage 時即 fatal "No ObservableObject of type AppLanguageStore found"。
    /// 兩者皆為 .shared singleton，重複注入冪等無害。所有設定入口統一走此。
    func settingsSheet(isPresented: Binding<Bool>) -> some View {
        toastSheet(isPresented: isPresented) {
            SettingsView()
                .environmentObject(AppLanguageStore.shared)
                .environmentObject(AppAppearanceStore.shared)
        }
    }
}

#Preview {
    SettingsView()
        .environmentObject(AppLanguageStore.shared)
        .environmentObject(AppAppearanceStore.shared)
}
