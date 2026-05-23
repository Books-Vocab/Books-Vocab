//
//  KGService+Request.swift
//  BooksBrowser
//
//  Authenticated HTTP middleware — token attach, retry, Sentry breadcrumbs.
//

import Foundation
import os

extension KGService {
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
        let requestID = RequestObservation.attachRequestID(to: &request)

        var lastError: Error?
        var retryAfterOverride: TimeInterval? = nil

        for attempt in 1...retryPolicy.maxAttempts {
            do {
                if attempt > 1 {
                    onRetry?(attempt - 1, retryPolicy.maxAttempts - 1)
                    let delay: TimeInterval
                    if let override = retryAfterOverride {
                        delay = override
                        retryAfterOverride = nil
                    } else {
                        delay = retryPolicy.baseDelay * pow(2.0, Double(attempt - 2))
                    }
                    try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
                }

                let (data, response) = try await sharedURLSession.data(for: request)

                guard let httpResponse = response as? HTTPURLResponse else {
                    throw KGError.serverError("Invalid response from \(path)")
                }
                let responseRequestID = RequestObservation.responseRequestID(from: httpResponse, fallback: requestID)
                Self.recordHTTPBreadcrumb(
                    url: url,
                    method: method,
                    statusCode: httpResponse.statusCode,
                    requestID: responseRequestID
                )

                if httpResponse.statusCode == 401 {
                    // 嘗試刷新 token 一次；若已刷新過仍 401 則放棄
                    if !didRefreshToken {
                        didRefreshToken = true
                        AppLog.kg.info("401 received for \(path) request_id=\(responseRequestID), attempting token refresh")
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
                    if attempt < retryPolicy.maxAttempts {
                        // 429: 優先使用伺服器的 Retry-After header（秒數格式，cap 60s）
                        if httpResponse.statusCode == 429,
                           let retryAfterValue = httpResponse.value(forHTTPHeaderField: "Retry-After"),
                           let seconds = TimeInterval(retryAfterValue) {
                            retryAfterOverride = min(seconds, 60)
                        }
                        continue
                    }
                }

                return (data, httpResponse)
            } catch let error as KGError {
                throw error // non-retryable KGError propagates immediately
            } catch let error as URLError {
                lastError = KGError.networkError(underlying: error)
                Self.recordHTTPBreadcrumb(
                    url: url,
                    method: method,
                    statusCode: nil,
                    requestID: requestID,
                    urlErrorCode: error.code.rawValue
                )
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

    /// Drop a Sentry breadcrumb describing one HTTP attempt.
    ///
    /// Privacy:
    /// - The URL is redacted to its path only — no host (already known via env tag),
    ///   no query string (where auth tokens / id_tokens / OAuth codes live).
    /// - The request_id is included so Sentry crumbs cross-correlate with backend
    ///   logs that already log + echo the same id via `X-Request-ID`.
    ///
    /// Levels:
    /// - 2xx/3xx → `.info`
    /// - 4xx/5xx → `.warning`
    /// - URLError (no HTTP exchange completed) → `.warning`
    private static func recordHTTPBreadcrumb(
        url: URL,
        method: String,
        statusCode: Int?,
        requestID: String?,
        urlErrorCode: Int? = nil
    ) {
        let redactedPath = URLComponents(url: url, resolvingAgainstBaseURL: false)?.path ?? url.path
        var data: [String: Any] = [
            "url": redactedPath,
            "method": method,
        ]
        if let statusCode { data["status_code"] = statusCode }
        if let requestID, !requestID.isEmpty { data["request_id"] = requestID }
        if let urlErrorCode { data["url_error_code"] = urlErrorCode }

        let level: AppCrashReporting.BreadcrumbLevel
        if let statusCode {
            level = (200..<400).contains(statusCode) ? .info : .warning
        } else {
            level = .warning  // transport failure — no HTTP response materialized
        }

        AppCrashReporting.addBreadcrumb(
            category: "http",
            message: "\(method) \(redactedPath)",
            level: level,
            data: data
        )
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
}
