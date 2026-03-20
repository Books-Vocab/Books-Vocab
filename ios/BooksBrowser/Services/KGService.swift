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

// MARK: - Service

/// Manages communication with the Knowledge Graph API server
@Observable
final class KGService: KGServing, LocalDataClearing {
    enum SyncKeys {
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

    @ObservationIgnored
    let userConfigClient: any KGUserConfigRemoteHandling

    var serverURL: String {
        get { Self.getServerURL() }
        set { Self.setServerURL(newValue) }
    }

    var isConnected: Bool = false
    var lastSyncDate: Date?
    var serverCardCount: Int = 0
    var sessionExpiredReason: String?

    /// 最近一次背景同步失敗訊息（UI 可觀測）
    var lastBackgroundSyncError: String?

    var baseURL: URL {
        var clean = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if !clean.hasPrefix("http://") && !clean.hasPrefix("https://") {
            clean = "http://" + clean
        }
        guard let url = URL(string: clean) ?? URL(string: Self.deployedServerURL) else {
            fatalError("Invalid deployedServerURL constant: \(Self.deployedServerURL)")
        }
        return url
    }

    init(
        authSession: any AuthSessionProviding = MainActor.assumeIsolated({ AuthManager.shared }),
        sessionInvalidator: any SessionInvalidating = MainActor.assumeIsolated({ AuthManager.shared }),
        userConfigClient: any KGUserConfigRemoteHandling = KGUserConfigClient()
    ) {
        self.authSession = authSession
        self.sessionInvalidator = sessionInvalidator
        self.userConfigClient = userConfigClient
    }

    // MARK: - Auth Helper

    func currentAuthToken() async throws -> String {
        guard NetworkMonitor.shared.isConnected else {
            throw KGError.offline
        }
        guard let token = await authSession.token else {
            throw KGError.unauthorized
        }
        if JWTExpiry.isExpired(token) {
            AppLog.kg.warning("Token expired (pre-check), triggering session invalidation")
            sessionExpiredReason = L10n.string("您的登入已過期，請重新登入")
            await sessionInvalidator.logout(modelContainer: nil, reason: "token_expired_precheck")
            throw KGError.unauthorized
        }
        return token
    }

    // MARK: - Session Invalidation (internal for extensions)

    func handleUnauthorized(modelContainer: ModelContainer?, reason: String) async {
        sessionExpiredReason = L10n.string("您的登入已過期，請重新登入")
        await sessionInvalidator.logout(modelContainer: modelContainer, reason: reason)
    }

    // MARK: - Authenticated Request Middleware

    func authenticatedRequest(
        path: String,
        method: String = "GET",
        queryItems: [URLQueryItem]? = nil,
        body: Data? = nil,
        retryPolicy: RetryPolicy = .default,
        onRetry: ((Int, Int) -> Void)? = nil
    ) async throws -> (Data, HTTPURLResponse) {
        var token = try await currentAuthToken()
        var didRefreshToken = false

        guard var components = URLComponents(
            url: baseURL.appendingPathComponent(path),
            resolvingAgainstBaseURL: false
        ) else {
            throw KGError.serverError("Invalid URL for \(path)")
        }
        if let queryItems, !queryItems.isEmpty {
            components.queryItems = queryItems
        }
        guard let url = components.url else {
            throw KGError.serverError("Invalid URL for \(path)")
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if body != nil {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        request.httpBody = body

        var lastError: Error?

        for attempt in 1...retryPolicy.maxAttempts {
            do {
                if attempt > 1 {
                    onRetry?(attempt - 1, retryPolicy.maxAttempts - 1)
                    let delay = retryPolicy.baseDelay * pow(2.0, Double(attempt - 2))
                    try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
                }

                let (data, response) = try await sharedURLSession.data(for: request)

                guard let httpResponse = response as? HTTPURLResponse else {
                    throw KGError.serverError("Invalid response from \(path)")
                }

                if httpResponse.statusCode == 401 {
                    // 嘗試刷新 token 一次；若已刷新過仍 401 則放棄
                    if !didRefreshToken {
                        didRefreshToken = true
                        AppLog.kg.info("401 received for \(path), attempting token refresh")
                        let newToken = try await currentAuthToken()
                        if newToken != token {
                            token = newToken
                            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                            continue
                        }
                    }
                    throw KGError.unauthorized
                }

                // Retryable HTTP status — retry if policy allows
                if retryPolicy.retryableStatusCodes.contains(httpResponse.statusCode) {
                    lastError = KGError.httpError(
                        statusCode: httpResponse.statusCode,
                        detail: String(data: data, encoding: .utf8) ?? "\(method) \(path) failed"
                    )
                    if attempt < retryPolicy.maxAttempts { continue }
                }

                return (data, httpResponse)
            } catch let error as KGError {
                throw error // non-retryable KGError propagates immediately
            } catch let error as URLError {
                lastError = KGError.networkError(underlying: error)
                switch error.code {
                case .timedOut, .networkConnectionLost:
                    if !NetworkMonitor.shared.isConnected { throw KGError.networkError(underlying: error) }
                    if attempt < retryPolicy.maxAttempts { continue }
                default:
                    throw KGError.networkError(underlying: error)
                }
            } catch {
                throw error
            }
        }

        throw lastError ?? KGError.serverError("Request failed after \(retryPolicy.maxAttempts) attempts")
    }

    func authenticatedDecode<T: Decodable>(
        _ type: T.Type,
        path: String,
        method: String = "GET",
        queryItems: [URLQueryItem]? = nil,
        body: Data? = nil,
        retryPolicy: RetryPolicy = .default,
        onRetry: ((Int, Int) -> Void)? = nil
    ) async throws -> T {
        let (data, httpResponse) = try await authenticatedRequest(
            path: path, method: method, queryItems: queryItems,
            body: body, retryPolicy: retryPolicy, onRetry: onRetry
        )
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.httpError(
                statusCode: httpResponse.statusCode,
                detail: String(data: data, encoding: .utf8) ?? "\(method) \(path) failed"
            )
        }
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            throw KGError.decodingError(underlying: error)
        }
    }

    func authenticatedVoid(
        path: String,
        method: String = "GET",
        queryItems: [URLQueryItem]? = nil,
        body: Data? = nil,
        retryPolicy: RetryPolicy = .none
    ) async throws {
        let (data, httpResponse) = try await authenticatedRequest(
            path: path, method: method, queryItems: queryItems,
            body: body, retryPolicy: retryPolicy
        )
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.httpError(
                statusCode: httpResponse.statusCode,
                detail: String(data: data, encoding: .utf8) ?? "\(method) \(path) failed"
            )
        }
    }

    // MARK: - Health Check

    func healthCheck() async {
        guard NetworkMonitor.shared.isConnected else {
            isConnected = false
            return
        }
        guard await authSession.isLoggedIn else {
            isConnected = false
            return
        }
        do {
            let (data, httpResponse) = try await authenticatedRequest(path: "api/health")

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
        } catch KGError.unauthorized {
            AppLog.kg.error("Health check failed: 401 Unauthorized")
            await handleUnauthorized(modelContainer: nil, reason: "healthcheck_401")
            isConnected = false
        } catch {
            isConnected = false
            AppLog.kg.error("Health check failed: \(error.localizedDescription)")
        }
    }

    // MARK: - Server URL Management

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
}

// MARK: - Retry Policy

struct RetryPolicy: Sendable {
    let maxAttempts: Int
    let baseDelay: TimeInterval
    let retryableStatusCodes: Set<Int>

    static let none = RetryPolicy(maxAttempts: 1, baseDelay: 0, retryableStatusCodes: [])
    static let `default` = RetryPolicy(maxAttempts: 3, baseDelay: 1.0, retryableStatusCodes: [429, 500, 502, 503])
    static let aggressive = RetryPolicy(maxAttempts: 5, baseDelay: 0.5, retryableStatusCodes: [429, 500, 502, 503])
}

// MARK: - Error

enum KGError: LocalizedError {
    case notAuthenticated
    case unauthorized
    case offline
    case httpError(statusCode: Int, detail: String)
    case decodingError(underlying: Error)
    case networkError(underlying: Error)
    case serverError(String)

    var errorDescription: String? {
        switch self {
        case .notAuthenticated, .unauthorized:
            return L10n.string("未登入帳號或身份已過期")
        case .offline:
            return L10n.string("目前沒有網路連線")
        case .httpError(let code, let detail):
            return L10n.format("HTTP %d：%@", code, detail)
        case .decodingError(let err):
            return L10n.format("解碼錯誤：%@", err.localizedDescription)
        case .networkError(let err):
            return L10n.format("網路錯誤：%@", err.localizedDescription)
        case .serverError(let msg):
            return L10n.format("KG 伺服器錯誤：%@", msg)
        }
    }

    var isNetworkRelated: Bool {
        switch self {
        case .offline, .networkError: return true
        default: return false
        }
    }

    var isRetryable: Bool {
        switch self {
        case .httpError(let code, _): return (500...599).contains(code) || code == 429
        case .offline, .networkError: return true
        default: return false
        }
    }
}
