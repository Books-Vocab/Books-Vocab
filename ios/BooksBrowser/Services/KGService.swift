//
//  KGService.swift
//  BooksBrowser
//
//  Knowledge Graph API client — communicates with the KG FastAPI server.
//

import Foundation
import SwiftData
import os

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
    let pronunciation: String?
}

struct KGGraphLink: Codable, Identifiable, Equatable {
    let id: String
    let fromId: String
    let toId: String
    let kind: String
    let confidence: Double
    let reason: String
}

struct KGOptionalIntegrationProviderConfig: Codable {
    let api_key: String?
}

struct KGUserIntegrationsConfig: Codable {
    let mochi: KGOptionalIntegrationProviderConfig?
}

struct KGTranslationConfig: Codable {
    let source_lang: String?
    let target_lang: String?
}

/// User config request/response
struct KGUserConfig: Codable {
    let integrations: KGUserIntegrationsConfig?
    let translation: KGTranslationConfig?

    init(
        optionalIntegrationKey: String?,
        integrations: KGUserIntegrationsConfig? = nil,
        translation: KGTranslationConfig? = nil
    ) {
        self.integrations = integrations ?? (
            optionalIntegrationKey == nil
                ? nil
                : KGUserIntegrationsConfig(
                    mochi: KGOptionalIntegrationProviderConfig(api_key: optionalIntegrationKey)
                )
        )
        self.translation = translation
    }

    var optionalIntegrationApiKey: String? {
        integrations?.mochi?.api_key
    }
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

// MARK: - KGSubscriptionStatus Convenience

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

    // MARK: - Date Formatting

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
        authSession: any AuthSessionProviding = MainActor.assumeIsolated({ AuthManager.shared }),
        sessionInvalidator: any SessionInvalidating = MainActor.assumeIsolated({ AuthManager.shared })
    ) {
        self.authSession = authSession
        self.sessionInvalidator = sessionInvalidator
    }

    // MARK: - Auth Helper

    private func currentAuthToken() async throws -> String {
        guard let token = await authSession.token else {
            throw KGError.unauthorized
        }
        return token
    }

    private func applyAuth(to request: inout URLRequest, token: String) {
        request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    }

    // MARK: - Health Check

    func healthCheck() async {
        guard await authSession.isLoggedIn else {
            isConnected = false
            return
        }
        do {
            let token = try await currentAuthToken()
            let url = baseURL.appendingPathComponent("api/health")
            var request = URLRequest(url: url)
            applyAuth(to: &request, token: token)

            let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

            guard let httpResponse = response as? HTTPURLResponse else {
                isConnected = false
                return
            }

            if httpResponse.statusCode == 401 {
                AppLog.kg.error("Health check failed: 401 Unauthorized")
                await sessionInvalidator.logout(modelContainer: nil, reason: "healthcheck_401")
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
            AppLog.kg.error("Health check failed: \(error.localizedDescription)")
        }
    }

    // MARK: - Delete Card

    func deleteCard(word: String) async throws {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/vocab/\(word)")
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        applyAuth(to: &request, token: token)

        let (_, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to delete '\(word)'")
        }
    }

    // MARK: - Archive / Unarchive

    func archiveCard(word: String, archived: Bool) async throws {
        let token = try await currentAuthToken()
        let encoded = word.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? word
        let url = baseURL.appendingPathComponent("api/vocab/\(encoded)/archive")
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        applyAuth(to: &request, token: token)
        request.httpBody = try JSONEncoder().encode(["archived": archived])

        let (_, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to archive '\(word)'")
        }
    }

    // MARK: - Batch Add Vocabulary

    func batchAdd(entries: [VocabularyEntry]) async throws -> KGAddResponse {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/vocab")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        applyAuth(to: &request, token: token)

        let payload = entries.map { entry in
            KGVocabEntry(
                word: entry.word,
                translation: entry.translation,
                context: entry.context,
                root_form: entry.rootForm,
                pronunciation: entry.pronunciation
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
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/pipeline")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        applyAuth(to: &request, token: token)

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
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/user/config")
        var request = URLRequest(url: url)
        applyAuth(to: &request, token: token)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to fetch config (HTTP \(httpResponse.statusCode))")
        }

        AppLog.kg.info("Fetched config successfully")
        return try JSONDecoder().decode(KGUserConfig.self, from: data)
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

    func updateUserConfig(optionalIntegrationKey: String?, translationConfig: KGTranslationConfig? = nil) async throws -> KGUserConfig {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/user/config")
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        applyAuth(to: &request, token: token)

        let payload = KGUserConfig(optionalIntegrationKey: optionalIntegrationKey, translation: translationConfig)
        request.httpBody = try JSONEncoder().encode(payload)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to update config (HTTP \(httpResponse.statusCode))")
        }

        AppLog.kg.info("Updated config successfully")
        return try JSONDecoder().decode(KGUserConfig.self, from: data)
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

    // MARK: - Push Review State

    func pushReviewStates(container: ModelContainer) async throws -> (updated: Int, skipped: Int) {
        let actor = BackgroundSyncActor(modelContainer: container)
        let payload = try await actor.buildReviewStatePushPayload()
        guard !payload.isEmpty else { return (0, 0) }

        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/vocab/review")
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        applyAuth(to: &request, token: token)

        request.httpBody = try JSONSerialization.data(withJSONObject: ["entries": payload])

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to push review state (HTTP \(httpResponse.statusCode))")
        }

        struct PushResponse: Decodable {
            let updated: Int
            let skipped: Int
        }
        let result = try JSONDecoder().decode(PushResponse.self, from: data)
        AppLog.kg.info("pushReviewStates: updated=\(result.updated), skipped=\(result.skipped)")
        return (result.updated, result.skipped)
    }

    // MARK: - Offline KG Sync logic

    /// Fetch all cards from KG API and merge them into local SwiftData VocabularyEntry items
    /// This makes all KG words available offline (for underlining and browsing).
    func pullCardsToLocal(container: ModelContainer, progress: ((String, Int, Int) -> Void)? = nil) async throws {
        let token = try await currentAuthToken()
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
            AppLog.kg.info("Performing incremental sync since: \(dateString)")
        } else {
            AppLog.kg.info("Performing full sync")
        }

        guard let url = urlComponents.url else {
            throw KGError.serverError("Invalid URL")
        }

        // Bug A fix: 記錄邊界在發起請求前，避免 pull 期間新增的卡片被跳過
        let pullBoundary = Date().timeIntervalSince1970

        var request = URLRequest(url: url)
        applyAuth(to: &request, token: token)

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
            AppLog.kg.error("Failed to decode KG cards: \(error.localizedDescription)")
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
        
        // 使用 pull 開始前的時間戳作為邊界，確保不遺漏 pull 期間的變更
        defaults.set(pullBoundary, forKey: SyncKeys.incrementalBoundary)
        defaults.set(SyncKeys.currentPayloadVersion, forKey: SyncKeys.payloadVersion)

        // Back-fill pronunciations for entries that are missing them (non-blocking)
        Task.detached(priority: .utility) {
            try? await actor.backfillPronunciations()
        }
    }
    
    /// Clears all local KG data (SwiftData + Sync Timestamp)
    func clearLocalData(container: ModelContainer, reason: String = "unspecified") async {
        let actor = BackgroundSyncActor(modelContainer: container)
        AppLog.kg.info("clearLocalData requested. reason=\(reason)")
        do {
            try await actor.clearVocabularyData(reason: reason)
        } catch {
            AppLog.kg.error("clearVocabularyData failed: \(error.localizedDescription)")
        }

        UserDefaults.standard.removeObject(forKey: SyncKeys.incrementalBoundary)
        lastSyncDate = nil
        serverCardCount = 0
    }

    // MARK: - Daily Review Stats Sync

    func pushDailyStats(container: ModelContainer) async throws -> Int {
        let actor = BackgroundSyncActor(modelContainer: container)
        let payload = try await actor.buildDailyStatsPushPayload()
        guard !payload.isEmpty else { return 0 }

        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/vocab/daily-stats")
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        applyAuth(to: &request, token: token)

        request.httpBody = try JSONSerialization.data(withJSONObject: ["entries": payload])

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to push daily stats (HTTP \(httpResponse.statusCode))")
        }

        struct PushResponse: Decodable { let upserted: Int }
        let result = try JSONDecoder().decode(PushResponse.self, from: data)
        AppLog.kg.info("pushDailyStats: upserted=\(result.upserted)")
        return result.upserted
    }

    func pullDailyStats(container: ModelContainer) async throws {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/vocab/daily-stats")
        var request = URLRequest(url: url)
        applyAuth(to: &request, token: token)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to pull daily stats (HTTP \(httpResponse.statusCode))")
        }

        struct StatsResponse: Decodable {
            struct Entry: Decodable {
                let day_key: String
                let total: Int
                let remembered: Int
                let forgot: Int
            }
            let entries: [Entry]
        }

        let decoded = try JSONDecoder().decode(StatsResponse.self, from: data)
        guard !decoded.entries.isEmpty else { return }

        let remoteStats: [[String: Any]] = decoded.entries.map {
            ["day_key": $0.day_key, "total": $0.total, "remembered": $0.remembered, "forgot": $0.forgot]
        }

        let actor = BackgroundSyncActor(modelContainer: container)
        try await actor.mergeDailyStats(remoteStats)
        AppLog.kg.info("pullDailyStats: merged \(decoded.entries.count) remote entries")
    }

    // MARK: - Background Sync (輕量：push review + pull)

    /// 自動背景同步 — 只推送複習狀態 + 每日統計 + 拉取最新卡片與統計
    func backgroundSync(container: ModelContainer) async {
        do {
            _ = try await pushReviewStates(container: container)
        } catch {
            AppLog.kg.warning("backgroundSync pushReview failed: \(error.localizedDescription)")
        }
        do {
            _ = try await pushDailyStats(container: container)
        } catch {
            AppLog.kg.warning("backgroundSync pushDailyStats failed: \(error.localizedDescription)")
        }
        do {
            try await pullCardsToLocal(container: container, progress: nil)
        } catch {
            AppLog.kg.warning("backgroundSync pull failed: \(error.localizedDescription)")
        }
        do {
            try await pullDailyStats(container: container)
        } catch {
            AppLog.kg.warning("backgroundSync pullDailyStats failed: \(error.localizedDescription)")
        }
    }

    /// 只推送複習狀態 + 每日統計（進背景時用）
    func pushReviewQuietly(container: ModelContainer) async {
        do {
            _ = try await pushReviewStates(container: container)
        } catch {
            AppLog.kg.warning("pushReviewQuietly failed: \(error.localizedDescription)")
        }
        do {
            _ = try await pushDailyStats(container: container)
        } catch {
            AppLog.kg.warning("pushReviewQuietly pushDailyStats failed: \(error.localizedDescription)")
        }
    }

    // MARK: - Fetch Graph Links
    
    func pullGraphLinks() async throws -> [KGGraphLink] {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/graph/links")
        var request = URLRequest(url: url)
        applyAuth(to: &request, token: token)
        
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
