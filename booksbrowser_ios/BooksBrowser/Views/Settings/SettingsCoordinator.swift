import Foundation
import SwiftData

@MainActor
final class SettingsCoordinator: ObservableObject {
    @Published var optionalIntegrationApiKey = ""
    @Published var fetchedKey = ""
    @Published var showOptionalIntegrationInfo = false
    @Published var connectionPulse = false
    @Published var iconBreathing = false
    @Published var showDeleteAccountConfirm = false
    @Published var isDeletingAccount = false
    @Published var deleteAccountError: String?
    @Published var manualLoginUserId = ""
    @Published var developerAccountId = ""
    @Published var debugLocalServerURL = ""

    private let developerAccountKey = "developer_account_id"
    private var saveTask: Task<Void, Never>?

    init() {
        developerAccountId = UserDefaults.standard.string(forKey: developerAccountKey) ?? ""
        #if DEBUG
        debugLocalServerURL = KGService.getDebugLocalServerURL()
        #endif
    }

    deinit {
        saveTask?.cancel()
    }

    func handleAppear() {
        iconBreathing = true
        manualLoginUserId = developerAccountId
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
                    optionalIntegrationKey: optionalIntegrationApiKey.isEmpty ? nil : optionalIntegrationApiKey
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

    func handleManualLogin(authManager: any AuthManaging) {
        let id = manualLoginUserId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty else { return }
        authManager.login(customToken: id)
    }

    func setDeveloperAccount() {
        developerAccountId = manualLoginUserId.trimmingCharacters(in: .whitespacesAndNewlines)
        UserDefaults.standard.set(developerAccountId, forKey: developerAccountKey)
    }

    func clearDeveloperAccount() {
        developerAccountId = ""
        UserDefaults.standard.removeObject(forKey: developerAccountKey)
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
