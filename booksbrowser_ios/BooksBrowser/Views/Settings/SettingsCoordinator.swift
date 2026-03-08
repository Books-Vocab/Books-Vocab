import Foundation
import SwiftData

@MainActor
final class SettingsCoordinator: ObservableObject {
    @Published var mochiApiKey = ""
    @Published var fetchedKey = ""
    @Published var showMochiInfo = false
    @Published var connectionPulse = false
    @Published var iconBreathing = false
    @Published var showDeleteAccountConfirm = false
    @Published var isDeletingAccount = false
    @Published var deleteAccountError: String?
    @Published var manualLoginUserId = ""
    @Published var developerAccountId = ""

    private let developerAccountKey = "developer_account_id"
    private var saveTask: Task<Void, Never>?

    init() {
        developerAccountId = UserDefaults.standard.string(forKey: developerAccountKey) ?? ""
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
                let fetched = config.mochi_api_key ?? ""
                fetchedKey = fetched
                mochiApiKey = fetched
            }
        } else {
            fetchedKey = ""
            mochiApiKey = ""
        }
    }

    func scheduleMochiSave(
        authManager: any AuthManaging,
        kgService: any KGServing
    ) {
        guard mochiApiKey != fetchedKey else { return }
        saveTask?.cancel()
        saveTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(600))
            guard !Task.isCancelled else { return }
            if authManager.isLoggedIn {
                _ = try? await kgService.updateUserConfig(mochiKey: mochiApiKey.isEmpty ? nil : mochiApiKey)
                fetchedKey = mochiApiKey
            }
        }
    }

    func requestDeleteAccount() {
        showDeleteAccountConfirm = true
    }

    func clearDeleteAccountError() {
        deleteAccountError = nil
    }

    func presentMochiInfo() {
        showMochiInfo = true
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
}
