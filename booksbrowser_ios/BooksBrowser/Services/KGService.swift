//
//  KGService.swift
//  BooksBrowser
//
//  Knowledge Graph API client — communicates with the KG FastAPI server.
//

import Foundation
import SwiftData

// MARK: - Models


/// KG server health response
struct KGHealthResponse: Codable {
    let status: String
    let cards: Int
    let links: Int
    let pendingCandidates: Int
    let lastModified: String?
}

/// Vocab add response
struct KGAddResponse: Codable {
    let created: Int
    let skipped: Int
    let duplicates: [String]
    let cardIds: [String: String]
}

/// Entry to send to KG server
struct KGVocabEntry: Codable {
    let word: String
    let translation: String
    let context: String
    let root_form: String?
}

struct KGGraphLink: Codable, Identifiable, Equatable {
    let id: String
    let fromId: String
    let toId: String
    let kind: String
    let confidence: Double
    let reason: String
}

/// User config request/response
struct KGUserConfig: Codable {
    let mochi_api_key: String?
}

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

// MARK: - Service

/// Manages communication with the Knowledge Graph API server
@Observable
final class KGService: KGServing, LocalDataClearing {
    private enum SyncKeys {
        static let incrementalBoundary = "kg_last_incremental_sync"
        static let payloadVersion = "kg_review_payload_version"
        static let currentPayloadVersion = 1
    }

    #if DEBUG
    enum DebugServerMode: String {
        case remote
        case local
    }

    private enum DebugServerKeys {
        static let mode = "kg_debug_server_mode"
        static let localURL = "kg_debug_local_server_url"
    }
    #endif

    // MARK: - Configuration

    private static let deployedServerURL = "https://wordnexus.lol"
    #if DEBUG
    private static let defaultLocalServerURL = "http://127.0.0.1:8000"
    #endif

    @ObservationIgnored
    private let authSession: any AuthSessionProviding

    @ObservationIgnored
    private let sessionInvalidator: any SessionInvalidating

    var serverURL: String {
        get { Self.getServerURL() }
        set { Self.setServerURL(newValue) }
    }

    var isConnected: Bool = false
    var lastSyncDate: Date?
    var serverCardCount: Int = 0

    private var baseURL: URL {
        var clean = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if !clean.hasPrefix("http://") && !clean.hasPrefix("https://") {
            clean = "http://" + clean
        }
        return URL(string: clean) ?? URL(string: Self.deployedServerURL)!
    }

    init(
        authSession: any AuthSessionProviding = AuthManager.shared,
        sessionInvalidator: any SessionInvalidating = AuthManager.shared
    ) {
        self.authSession = authSession
        self.sessionInvalidator = sessionInvalidator
    }

    // MARK: - Auth Helper

    private func applyAuth(to request: inout URLRequest) throws {
        guard let token = authSession.token else {
            throw KGError.unauthorized
        }
        request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    }

    // MARK: - Health Check

    func healthCheck() async {
        guard authSession.isLoggedIn else {
            isConnected = false
            return
        }
        do {
            let url = baseURL.appendingPathComponent("api/health")
            var request = URLRequest(url: url)
            try applyAuth(to: &request)
            
            let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

            guard let httpResponse = response as? HTTPURLResponse else {
                isConnected = false
                return
            }
            
            if httpResponse.statusCode == 401 {
                print("❌ KG health check failed: 401 Unauthorized")
                sessionInvalidator.logout(modelContainer: nil, reason: "healthcheck_401")
                isConnected = false
                return
            }
            
            if httpResponse.statusCode != 200 {
                isConnected = false
                return
            }

            let health = try JSONDecoder().decode(KGHealthResponse.self, from: data)
            isConnected = health.status == "ok"
            serverCardCount = health.cards

            if let lastModStr = health.lastModified {
                let formatter = ISO8601DateFormatter()
                formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                lastSyncDate = formatter.date(from: lastModStr)
            }
        } catch {
            isConnected = false
            print("❌ KG health check failed: \(error)")
        }
    }

    // MARK: - Delete Card

    func deleteCard(word: String) async throws {
        let url = baseURL.appendingPathComponent("api/vocab/\(word)")
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        try applyAuth(to: &request)

        let (_, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to delete '\(word)'")
        }
    }

    // MARK: - Batch Add Vocabulary

    func batchAdd(entries: [VocabularyEntry]) async throws -> KGAddResponse {
        let url = baseURL.appendingPathComponent("api/vocab")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        try applyAuth(to: &request)

        let payload = entries.map { entry in
            KGVocabEntry(
                word: entry.word,
                translation: entry.translation,
                context: entry.context,
                root_form: entry.rootForm
            )
        }

        request.httpBody = try JSONEncoder().encode(payload)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to add vocabulary")
        }

        return try JSONDecoder().decode(KGAddResponse.self, from: data)
    }

    // MARK: - Trigger Pipeline (Fire-and-forget)

    func triggerPipeline() async throws {
        let url = baseURL.appendingPathComponent("api/pipeline")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        try applyAuth(to: &request)

        let (_, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Pipeline failed to start (HTTP \(httpResponse.statusCode))")
        }
    }

    // MARK: - API Key Management

    static func setServerURL(_ url: String) {
        #if DEBUG
        let normalized = normalizeServerURL(url)
        if normalized == deployedServerURL {
            useProductionServer()
            return
        }
        UserDefaults.standard.set(normalized, forKey: DebugServerKeys.localURL)
        UserDefaults.standard.set(DebugServerMode.local.rawValue, forKey: DebugServerKeys.mode)
        #else
        _ = url
        #endif
    }

    static func getServerURL() -> String {
        #if DEBUG
        switch getDebugServerMode() {
        case .remote:
            return deployedServerURL
        case .local:
            return getDebugLocalServerURL()
        }
        #else
        return deployedServerURL
        #endif
    }

    #if DEBUG
    static func getDebugServerMode() -> DebugServerMode {
        let raw = UserDefaults.standard.string(forKey: DebugServerKeys.mode) ?? DebugServerMode.remote.rawValue
        return DebugServerMode(rawValue: raw) ?? .remote
    }

    static func getDebugLocalServerURL() -> String {
        let stored = UserDefaults.standard.string(forKey: DebugServerKeys.localURL)
        return normalizeServerURL(stored ?? defaultLocalServerURL)
    }

    static func setDebugLocalServerURL(_ url: String) {
        UserDefaults.standard.set(normalizeServerURL(url), forKey: DebugServerKeys.localURL)
    }

    static func useProductionServer() {
        UserDefaults.standard.set(DebugServerMode.remote.rawValue, forKey: DebugServerKeys.mode)
    }

    static func useLocalServer() {
        UserDefaults.standard.set(DebugServerMode.local.rawValue, forKey: DebugServerKeys.mode)
    }

    private static func normalizeServerURL(_ url: String) -> String {
        let trimmed = url.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return defaultLocalServerURL }
        return trimmed.hasSuffix("/") ? String(trimmed.dropLast()) : trimmed
    }
    #endif

    // MARK: - User Configuration

    func fetchUserConfig() async throws -> KGUserConfig {
        let url = baseURL.appendingPathComponent("api/user/config")
        var request = URLRequest(url: url)
        try applyAuth(to: &request)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to fetch config (HTTP \(httpResponse.statusCode))")
        }

        print("✅ [KGService] Fetched config successfully")
        return try JSONDecoder().decode(KGUserConfig.self, from: data)
    }

    func fetchEntitlements() async throws -> KGEntitlements {
        let url = baseURL.appendingPathComponent("api/user/entitlements")
        var request = URLRequest(url: url)
        try applyAuth(to: &request)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to fetch entitlements (HTTP \(httpResponse.statusCode))")
        }

        print("✅ [KGService] Fetched entitlements successfully")
        return try JSONDecoder().decode(KGEntitlements.self, from: data)
    }

    func syncAppStoreSubscription(_ snapshot: KGAppStoreSubscriptionSyncRequest) async throws -> KGEntitlements {
        let url = baseURL.appendingPathComponent("api/billing/app-store/sync")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        try applyAuth(to: &request)
        request.httpBody = try JSONEncoder().encode(snapshot)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to sync subscription (HTTP \(httpResponse.statusCode))")
        }

        print("✅ [KGService] Synced App Store subscription successfully")
        return try JSONDecoder().decode(KGEntitlements.self, from: data)
    }

    func updateUserConfig(mochiKey: String?) async throws -> KGUserConfig {
        let url = baseURL.appendingPathComponent("api/user/config")
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        try applyAuth(to: &request)

        let payload = KGUserConfig(mochi_api_key: mochiKey)
        request.httpBody = try JSONEncoder().encode(payload)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to update config (HTTP \(httpResponse.statusCode))")
        }

        print("✅ [KGService] Updated config successfully")
        return try JSONDecoder().decode(KGUserConfig.self, from: data)
    }

    func deleteAccount() async throws {
        let url = baseURL.appendingPathComponent("api/user/account")
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        try applyAuth(to: &request)

        let (_, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to delete account (HTTP \(httpResponse.statusCode))")
        }
    }

    // MARK: - Offline KG Sync logic

    /// Fetch all cards from KG API and merge them into local SwiftData VocabularyEntry items
    /// This makes all KG words available offline (for underlining and browsing).
    func pullCardsToLocal(container: ModelContainer, progress: ((String, Int, Int) -> Void)? = nil) async throws {
        progress?(L10n.string("從遠端下載知識庫..."), 0, 0)

        let defaults = UserDefaults.standard
        let storedPayloadVersion = defaults.integer(forKey: SyncKeys.payloadVersion)
        if storedPayloadVersion < SyncKeys.currentPayloadVersion {
            defaults.removeObject(forKey: SyncKeys.incrementalBoundary)
            progress?(L10n.string("升級卡片資料格式，重新同步全部卡片..."), 0, 0)
        }
        
        var urlComponents = URLComponents(url: baseURL.appendingPathComponent("api/vocab"), resolvingAgainstBaseURL: false)!
        
        let lastSyncMillis = defaults.double(forKey: SyncKeys.incrementalBoundary)
        let isIncremental = lastSyncMillis > 0
        
        if isIncremental {
            let lastSyncDate = Date(timeIntervalSince1970: lastSyncMillis)
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let dateString = formatter.string(from: lastSyncDate)
            urlComponents.queryItems = [URLQueryItem(name: "since", value: dateString)]
            print("🔄 Performing incremental sync since: \(dateString)")
        } else {
            print("🔄 Performing full sync")
        }
        
        guard let url = urlComponents.url else {
            throw KGError.serverError("Invalid URL")
        }
        
        var request = URLRequest(url: url)
        try applyAuth(to: &request)
        
        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to fetch cards, HTTP \(httpResponse.statusCode)")
        }

        progress?(L10n.string("解析資料..."), 0, 0)
        let fetchedCards: [KGCard]
        do {
            fetchedCards = try JSONDecoder().decode([KGCard].self, from: data)
        } catch {
            print("❌ Failed to decode KG cards: \(error)")
            throw KGError.serverError("Parse error: \(error.localizedDescription)")
        }

        // Let the new Actor handle SwiftData operations safely off the main thread.
        let actor = BackgroundSyncActor(modelContainer: container)
        try await actor.pullCardsToLocal(
            fetchedCards: fetchedCards,
            isIncremental: isIncremental,
            progress: { detail, current, total in
                progress?(detail, current, total)
            }
        )
        
        // Save the successful sync boundary to avoid re-fetching later
        defaults.set(Date().timeIntervalSince1970, forKey: SyncKeys.incrementalBoundary)
        defaults.set(SyncKeys.currentPayloadVersion, forKey: SyncKeys.payloadVersion)
    }
    
    /// Clears all local KG data (SwiftData + Sync Timestamp)
    func clearLocalData(container: ModelContainer, reason: String = "unspecified") async {
        let actor = BackgroundSyncActor(modelContainer: container)
        print("🧹 clearLocalData requested. reason=\(reason)")
        try? await actor.clearVocabularyData(reason: reason)
        
        UserDefaults.standard.removeObject(forKey: SyncKeys.incrementalBoundary)
        lastSyncDate = nil
        serverCardCount = 0
    }

    // MARK: - Fetch Graph Links
    
    func pullGraphLinks() async throws -> [KGGraphLink] {
        let url = baseURL.appendingPathComponent("api/graph/links")
        var request = URLRequest(url: url)
        try applyAuth(to: &request)
        
        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to fetch graph links, HTTP \(httpResponse.statusCode)")
        }
        
        return try JSONDecoder().decode([KGGraphLink].self, from: data)
    }
}

// MARK: - Error

enum KGError: LocalizedError {
    case serverError(String)
    case notConnected
    case unauthorized

    var errorDescription: String? {
        switch self {
        case .serverError(let msg): return L10n.format("KG 伺服器錯誤：%@", msg)
        case .notConnected: return L10n.string("KG 伺服器未連線")
        case .unauthorized: return L10n.string("未登入帳號或身份已過期")
        }
    }
}
