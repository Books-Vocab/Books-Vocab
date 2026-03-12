//
//  KGService+UserConfig.swift
//  BooksBrowser
//

import Foundation

// MARK: - Subscription & Billing Models

struct KGSubscriptionStatus: Codable, Equatable {
    let is_active: Bool
    let product_id: String?
    let plan_name: String?
    let price_display: String?
    let status: String
    let is_trial: Bool
    let trial_days: Int?
    let will_renew: Bool
    let expires_at: String?
    let source: String
    let last_synced_at: String?
}

extension KGSubscriptionStatus {
    var isCancelledButActive: Bool {
        is_active && !will_renew && source != "admin"
    }

    var formattedExpiryDate: String {
        Self.formattedExpiry(expires_at)
    }

    var isExpired: Bool {
        guard let expires_at, !expires_at.isEmpty,
              let date = Self.parseExpiryDate(expires_at) else { return false }
        return date < Date()
    }

    static func parseExpiryDate(_ isoString: String) -> Date? {
        expiryISO8601Formatter.date(from: isoString) ?? expiryISO8601FallbackFormatter.date(from: isoString)
    }

    private static let expiryISO8601Formatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    private static let expiryISO8601FallbackFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private static let expiryDisplayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy/MM/dd HH:mm"
        f.locale = Locale(identifier: "zh_TW")
        return f
    }()

    static func formattedExpiry(_ isoString: String?) -> String {
        guard let isoString, !isoString.isEmpty else {
            return L10n.string("未知時間")
        }
        if let date = expiryISO8601Formatter.date(from: isoString)
            ?? expiryISO8601FallbackFormatter.date(from: isoString) {
            return expiryDisplayFormatter.string(from: date)
        }
        return isoString
    }
}

struct KGEntitlements: Codable, Equatable {
    let pro: KGSubscriptionStatus
}

struct KGAppStoreSubscriptionSyncRequest: Codable {
    let product_id: String
    let transaction_id: String?
    let original_transaction_id: String?
    let environment: String
    let status: String
    let is_trial: Bool
    let expires_at: String?
    let will_renew: Bool
    let price_display: String?
    let signed_transaction_info: String?
}

// MARK: - User Configuration & Account

extension KGService {

    func fetchUserConfig() async throws -> KGUserConfig {
        let token = try await currentAuthToken()
        let config = try await userConfigClient.fetchUserConfig(baseURL: baseURL, token: token)
        AppLog.kg.info("Fetched config successfully")
        return config
    }

    func fetchEntitlements() async throws -> KGEntitlements {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/user/entitlements")
        var request = URLRequest(url: url)
        applyAuth(to: &request, token: token)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to fetch entitlements (HTTP \(httpResponse.statusCode))")
        }

        AppLog.kg.info("Fetched entitlements successfully")
        return try JSONDecoder().decode(KGEntitlements.self, from: data)
    }

    func syncAppStoreSubscription(_ snapshot: KGAppStoreSubscriptionSyncRequest) async throws -> KGEntitlements {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/billing/app-store/sync")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        applyAuth(to: &request, token: token)
        request.httpBody = try JSONEncoder().encode(snapshot)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to sync subscription (HTTP \(httpResponse.statusCode))")
        }

        AppLog.kg.info("Synced App Store subscription successfully")
        return try JSONDecoder().decode(KGEntitlements.self, from: data)
    }

    func updateOptionalIntegrationKey(_ apiKey: String) async throws -> KGUserConfig {
        let token = try await currentAuthToken()
        let config = try await userConfigClient.updateOptionalIntegrationKey(
            baseURL: baseURL,
            token: token,
            apiKey: apiKey
        )
        AppLog.kg.info("Updated config successfully")
        return config
    }

    func updateTranslationConfig(_ translationConfig: KGTranslationConfig) async throws -> KGUserConfig {
        let token = try await currentAuthToken()
        let config = try await userConfigClient.updateTranslationConfig(
            baseURL: baseURL,
            token: token,
            translation: translationConfig
        )
        AppLog.kg.info("Updated translation config successfully")
        return config
    }

    func deleteAccount() async throws {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/user/account")
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        applyAuth(to: &request, token: token)

        let (_, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to delete account (HTTP \(httpResponse.statusCode))")
        }
    }
}
