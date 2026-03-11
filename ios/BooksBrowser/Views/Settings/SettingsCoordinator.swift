import Foundation
import SwiftData

@Observable @MainActor
final class SettingsCoordinator {
    var optionalIntegrationApiKey = ""
    var fetchedKey = ""
    var showOptionalIntegrationInfo = false
    var connectionPulse = false
    var iconBreathing = false
    var showDeleteAccountConfirm = false
    var isDeletingAccount = false
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
                let fetched = config.optionalIntegrationApiKey ?? ""
                fetchedKey = fetched
                optionalIntegrationApiKey = fetched

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
        kgService: any KGServing
    ) {
        guard optionalIntegrationApiKey != fetchedKey else { return }
        saveTask?.cancel()
        saveTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(600))
            guard !Task.isCancelled else { return }
            if authManager.isLoggedIn {
                _ = try? await kgService.updateUserConfig(
                    optionalIntegrationKey: optionalIntegrationApiKey.isEmpty ? nil : optionalIntegrationApiKey,
                    translationConfig: nil
                )
                fetchedKey = optionalIntegrationApiKey
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
        kgService: any KGServing
    ) {
        translationSourceLang = source
        translationTargetLang = target
        TranslationLanguage.currentSource = source
        TranslationLanguage.currentTarget = target

        guard authManager.isLoggedIn else { return }
        Task { @MainActor in
            _ = try? await kgService.updateUserConfig(
                optionalIntegrationKey: nil,
                translationConfig: KGTranslationConfig(
                    source_lang: source.rawValue,
                    target_lang: target.rawValue
                )
            )
        }
    }

    func handleManualLogin(authManager: any AuthManaging) {
        let id = manualLoginUserId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty else { return }
        authManager.login(customToken: id)
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
