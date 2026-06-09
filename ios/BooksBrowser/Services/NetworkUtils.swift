//
//  NetworkUtils.swift
//  Books & Vocab
//
//  共用網路工具：統一 URLSession（8s timeout）+ exponential backoff retry
//

import Foundation

// MARK: - Constants

private let requestTimeoutSeconds: TimeInterval = 8
private let resourceTimeoutSeconds: TimeInterval = 60
private let retryBackoffBaseSeconds = 0.5

// MARK: - Shared URLSession

let sharedURLSession: URLSession = {
    let config = URLSessionConfiguration.default
    config.timeoutIntervalForRequest = requestTimeoutSeconds
    config.timeoutIntervalForResource = resourceTimeoutSeconds
    return URLSession(configuration: config)
}()

// MARK: - withRetry

/// 帶 exponential backoff 的重試包裹器（0.5s, 1.0s）
/// - 重試條件：URLError 網路層異常（timeout、無連線、連線中斷）+ HTTP 5xx
func withRetry<T>(
    maxRetries: Int = 2,
    onRetry: ((Int, Int) -> Void)? = nil,
    operation: () async throws -> T
) async throws -> T {
    var lastError: Error?

    for attempt in 0...maxRetries {
        do {
            if attempt > 0 {
                onRetry?(attempt, maxRetries)
                let delay = Double(attempt) * retryBackoffBaseSeconds
                try await Task.sleep(for: .seconds(delay))
            }
            let result = try await operation()

            // HTTP 5xx retry: 若 T 是 (Data, URLResponse) tuple，檢查 status code
            if let tuple = result as? (Data, URLResponse),
               let http = tuple.1 as? HTTPURLResponse,
               (500...599).contains(http.statusCode) {
                lastError = URLError(.badServerResponse)
                if attempt < maxRetries {
                    continue
                }
            }

            return result
        } catch let error as URLError {
            lastError = error
            switch error.code {
            case .timedOut, .networkConnectionLost:
                // 離線時不重試，直接 fail fast
                if !NetworkMonitor.shared.isConnected {
                    throw error
                }
                continue
            case .notConnectedToInternet:
                throw error
            default:
                throw error
            }
        } catch {
            throw error
        }
    }

    throw lastError ?? URLError(.timedOut)
}
