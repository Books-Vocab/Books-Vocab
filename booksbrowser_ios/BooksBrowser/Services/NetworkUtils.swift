//
//  NetworkUtils.swift
//  BooksBrowser
//
//  共用網路工具：統一 URLSession（8s timeout）+ exponential backoff retry
//

import Foundation

// MARK: - Shared URLSession

let sharedURLSession: URLSession = {
    let config = URLSessionConfiguration.default
    config.timeoutIntervalForRequest = 8
    config.timeoutIntervalForResource = 60
    return URLSession(configuration: config)
}()

// MARK: - withRetry

/// 帶 exponential backoff 的重試包裹器（0.5s, 1.0s）
/// - 重試條件：URLError 網路層異常（timeout、無連線、連線中斷）
/// - 應用層錯誤（HTTP 4xx/5xx）由呼叫方自行決策，不在此重試
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
                let delay = Double(attempt) * 0.5
                try await Task.sleep(for: .seconds(delay))
            }
            return try await operation()
        } catch let error as URLError {
            lastError = error
            switch error.code {
            case .timedOut, .notConnectedToInternet, .networkConnectionLost:
                continue
            default:
                throw error
            }
        } catch {
            throw error
        }
    }

    throw lastError ?? URLError(.timedOut)
}
