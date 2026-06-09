//
//  RetryPolicy.swift
//  Books & Vocab
//
//  Retry behavior config for KG authenticated requests.
//

import Foundation

struct RetryPolicy: Sendable {
    let maxAttempts: Int
    let baseDelay: TimeInterval
    let retryableStatusCodes: Set<Int>

    static let none = RetryPolicy(maxAttempts: 1, baseDelay: 0, retryableStatusCodes: [])
    static let `default` = RetryPolicy(maxAttempts: 3, baseDelay: 1.0, retryableStatusCodes: [429, 500, 502, 503, 504])
    static let aggressive = RetryPolicy(maxAttempts: 5, baseDelay: 0.5, retryableStatusCodes: [429, 500, 502, 503, 504])
}
