import Foundation
import SwiftData
import os

@MainActor protocol SettingsCoordinating: AnyObject, Observable {
    var showSubscriptionPaywall: Bool { get set }
    var connectionPulse: Bool { get }
    var iconBreathing: Bool { get }
    var showDeleteAccountConfirm: Bool { get set }
    var isDeletingAccount: Bool { get }
    var deleteAccountError: String? { get }
    var translationSourceLang: TranslationLanguage { get set }
    var translationTargetLang: TranslationLanguage { get set }
    func handleAppear()
    func loadData(authManager: any AuthManaging, kgService: any KGServing) async
    func requestDeleteAccount()
    func clearDeleteAccountError()
    func presentSubscriptionPaywall()
    func deleteAccount(authManager: any AuthManaging, kgService: any KGServing, modelContext: ModelContext) async
    func updateTranslationLanguage(source: TranslationLanguage, target: TranslationLanguage, authManager: any AuthManaging, kgService: any KGServing, toastCoordinator: AppToastCoordinator)
}

@Observable @MainActor
final class SettingsCoordinator: SettingsCoordinating {
    var showSubscriptionPaywall = false
    var connectionPulse = false
    var iconBreathing = false
    var showDeleteAccountConfirm = false
    var isDeletingAccount = false
    var isResyncing = false
    var deleteAccountError: String?
    var manualLoginUserId = ""
    var debugLocalServerURL = ""
    var observationPreviewLines: [String] = []
    var observationTotalCount = 0
    var translationSourceLang: TranslationLanguage = TranslationLanguage.currentSource
    var translationTargetLang: TranslationLanguage = TranslationLanguage.currentTarget
    init() {
        #if DEBUG
        debugLocalServerURL = KGService.getDebugLocalServerURL()
        #endif
    }

    func handleAppear() {
        iconBreathing = true
        refreshObservationPreview()
    }

    func loadData(
        authManager: any AuthManaging,
        kgService: any KGServing
    ) async {
        refreshObservationPreview()
        await kgService.healthCheck()
        connectionPulse.toggle()

        if authManager.isLoggedIn {
            if let config = try? await kgService.fetchUserConfig() {
                // Sync translation language from server config
                if let translation = config.translation {
                    if let src = translation.source_lang, let lang = TranslationLanguage(rawValue: src) {
                        translationSourceLang = lang
                        TranslationLanguage.currentSource = lang
                    }
                    if let tgt = translation.target_lang, let lang = TranslationLanguage(rawValue: tgt) {
                        translationTargetLang = lang
                        TranslationLanguage.currentTarget = lang
                    }
                }
            }
        }
    }

    func refreshObservationPreview() {
        let preview = AppObservationStore.shared.preview()
        observationPreviewLines = preview.entries.map(\.previewLine)
        observationTotalCount = preview.totalCount
    }

    func requestDeleteAccount() {
        showDeleteAccountConfirm = true
    }

    func clearDeleteAccountError() {
        deleteAccountError = nil
    }

    func presentSubscriptionPaywall() {
        showSubscriptionPaywall = true
    }

    func deleteAccount(
        authManager: any AuthManaging,
        kgService: any KGServing,
        modelContext: ModelContext
    ) async {
        guard authManager.isLoggedIn, !isDeletingAccount else { return }
        isDeletingAccount = true
        defer { isDeletingAccount = false }

        do {
            try await kgService.deleteAccount()
            authManager.logout(modelContainer: modelContext.container, reason: "delete_account")
        } catch {
            deleteAccountError = L10n.format("無法刪除帳號：%@", error.localizedDescription)
        }
    }

    func updateTranslationLanguage(
        source: TranslationLanguage,
        target: TranslationLanguage,
        authManager: any AuthManaging,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) {
        translationSourceLang = source
        translationTargetLang = target
        TranslationLanguage.currentSource = source
        TranslationLanguage.currentTarget = target

        guard authManager.isLoggedIn else { return }
        Task {
            do {
                _ = try await kgService.updateTranslationConfig(
                    KGTranslationConfig(
                        source_lang: source.rawValue,
                        target_lang: target.rawValue
                    )
                )
            } catch {
                toastCoordinator.error("設定儲存失敗")
                AppLog.kg.error("updateUserConfig (translation lang) failed: \(error.localizedDescription)")
            }
        }
    }

    func handleManualLogin(authManager: any AuthManaging) {
        let id = manualLoginUserId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty else { return }
        authManager.login(customToken: id)
    }

    func resync(kgService: any KGServing, modelContext: ModelContext) async {
        guard !isResyncing else { return }
        isResyncing = true
        defer { isResyncing = false }
        await kgService.backgroundSync(container: modelContext.container)
        try? modelContext.container.mainContext.save()
        await kgService.healthCheck()
        await kgService.fetchQuota()
        refreshObservationPreview()
    }

    #if DEBUG
    func useProductionBackend(
        authManager: any AuthManaging,
        kgService: any KGServing
    ) async {
        KGService.useProductionServer()
        debugLocalServerURL = KGService.getDebugLocalServerURL()
        await loadData(authManager: authManager, kgService: kgService)
        refreshObservationPreview()
    }

    func useLocalBackend(
        authManager: any AuthManaging,
        kgService: any KGServing
    ) async {
        KGService.setDebugLocalServerURL(debugLocalServerURL)
        KGService.useLocalServer()
        debugLocalServerURL = KGService.getDebugLocalServerURL()
        await loadData(authManager: authManager, kgService: kgService)
        refreshObservationPreview()
    }
    #endif
}
