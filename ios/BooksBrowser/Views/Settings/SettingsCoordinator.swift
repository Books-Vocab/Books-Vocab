import Foundation
import SwiftData
import os

@MainActor protocol SettingsCoordinating: AnyObject, Observable {
    var optionalIntegrationApiKey: String { get set }
    var fetchedKey: String { get }
    var showOptionalIntegrationInfo: Bool { get set }
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
    func scheduleOptionalIntegrationSave(authManager: any AuthManaging, kgService: any KGServing, toastCoordinator: AppToastCoordinator)
    func requestDeleteAccount()
    func clearDeleteAccountError()
    func presentOptionalIntegrationInfo()
    func presentSubscriptionPaywall()
    func deleteAccount(authManager: any AuthManaging, kgService: any KGServing, modelContext: ModelContext) async
    func updateTranslationLanguage(source: TranslationLanguage, target: TranslationLanguage, authManager: any AuthManaging, kgService: any KGServing, toastCoordinator: AppToastCoordinator)
}

@Observable @MainActor
final class SettingsCoordinator: SettingsCoordinating {
    var optionalIntegrationApiKey = ""
    var fetchedKey = ""
    var showOptionalIntegrationInfo = false
    var showSubscriptionPaywall = false
    var connectionPulse = false
    var iconBreathing = false
    var showDeleteAccountConfirm = false
    var isDeletingAccount = false
    var isResyncing = false
    var deleteAccountError: String?
    var manualLoginUserId = ""
    var debugLocalServerURL = ""
    var translationSourceLang: TranslationLanguage = TranslationLanguage.currentSource
    var translationTargetLang: TranslationLanguage = TranslationLanguage.currentTarget
    @ObservationIgnored private var saveTask: Task<Void, Never>?

    init() {
        #if DEBUG
        debugLocalServerURL = KGService.getDebugLocalServerURL()
        #endif
    }

    deinit {
        saveTask?.cancel()
    }

    func handleAppear() {
        iconBreathing = true
    }

    func loadData(
        authManager: any AuthManaging,
        kgService: any KGServing
    ) async {
        await kgService.healthCheck()
        connectionPulse.toggle()

        if authManager.isLoggedIn {
            if let config = try? await kgService.fetchUserConfig() {
                if let key = config.optionalIntegrationApiKey, !key.isEmpty {
                    fetchedKey = key
                    optionalIntegrationApiKey = key
                } else if config.hasMochiApiKey {
                    let placeholder = "••••••••"
                    fetchedKey = placeholder
                    optionalIntegrationApiKey = placeholder
                } else {
                    fetchedKey = ""
                    optionalIntegrationApiKey = ""
                }

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
        } else {
            fetchedKey = ""
            optionalIntegrationApiKey = ""
        }
    }

    func scheduleOptionalIntegrationSave(
        authManager: any AuthManaging,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) {
        guard optionalIntegrationApiKey != fetchedKey else { return }
        saveTask?.cancel()
        saveTask = Task {
            try? await Task.sleep(for: .milliseconds(600))
            guard !Task.isCancelled else { return }
            if authManager.isLoggedIn {
                do {
                    let sent = optionalIntegrationApiKey
                    let config = try await kgService.updateOptionalIntegrationKey(sent)
                    if config.hasMochiApiKey {
                        let placeholder = "••••••••"
                        fetchedKey = placeholder
                        optionalIntegrationApiKey = placeholder
                    } else {
                        fetchedKey = ""
                        optionalIntegrationApiKey = ""
                    }
                } catch {
                    toastCoordinator.error("儲存失敗")
                    AppLog.kg.error("updateUserConfig (API key) failed: \(error.localizedDescription)")
                    return
                }
            }
        }
    }

    func requestDeleteAccount() {
        showDeleteAccountConfirm = true
    }

    func clearDeleteAccountError() {
        deleteAccountError = nil
    }

    func presentOptionalIntegrationInfo() {
        showOptionalIntegrationInfo = true
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
    }

    #if DEBUG
    func useProductionBackend(
        authManager: any AuthManaging,
        kgService: any KGServing
    ) async {
        KGService.useProductionServer()
        debugLocalServerURL = KGService.getDebugLocalServerURL()
        await loadData(authManager: authManager, kgService: kgService)
    }

    func useLocalBackend(
        authManager: any AuthManaging,
        kgService: any KGServing
    ) async {
        KGService.setDebugLocalServerURL(debugLocalServerURL)
        KGService.useLocalServer()
        debugLocalServerURL = KGService.getDebugLocalServerURL()
        await loadData(authManager: authManager, kgService: kgService)
    }
    #endif
}
