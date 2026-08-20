//
//  SentryPrivacyPolicy.swift
//  Books & Vocab
//
//  Centralized, deterministic redaction rules for diagnostics. This layer is
//  deliberately strict: unknown breadcrumb fields are dropped instead of
//  guessing whether a value is safe.
//

import Foundation

enum SentryPrivacyPolicy {
    private static let opaqueIDPattern = try! NSRegularExpression(pattern: "^[A-Za-z0-9._:-]{1,128}$")
    private static let labelPattern = try! NSRegularExpression(pattern: "^[A-Za-z0-9._:/-]{1,128}$")
    private static let safeBreadcrumbKeys: Set<String> = [
        "attempt", "duration_ms", "error_type", "feature", "format", "method", "operation",
        "phase", "provider", "request_id", "result", "retry_count", "status_code", "url",
        "url_error_code"
    ]
    private static let sensitiveKeyFragments = [
        "authorization", "cookie", "email", "input", "password", "query", "secret", "text",
        "token", "user", "body", "content", "card", "book", "translation"
    ]

    static func stripQuery(from value: String) -> String {
        guard let questionMark = value.firstIndex(of: "?") else { return value }
        return String(value[..<questionMark])
    }

    static func redactRequestID(_ value: String?) -> String? {
        guard let value else { return nil }
        return redactOpaqueID(value)
    }

    static func redactUserID(_ value: String?) -> String? {
        guard let value, !value.contains("@") else { return nil }
        return redactOpaqueID(value)
    }

    static func redactOpaqueID(_ value: String?) -> String? {
        guard let value else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard matches(opaqueIDPattern, value: trimmed) else { return nil }
        return trimmed
    }

    static func redactContext(_ value: String?) -> String? {
        guard let value else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard matches(labelPattern, value: trimmed) else { return nil }
        return trimmed
    }

    static func redactBreadcrumbMessage(_ value: String?) -> String? {
        guard let value else { return nil }
        let stripped = stripQuery(from: value.trimmingCharacters(in: .whitespacesAndNewlines))
        guard !stripped.isEmpty, stripped.count <= 160 else { return nil }
        let lowercased = stripped.lowercased()
        if sensitiveKeyFragments.contains(where: { lowercased.contains("\($0)=") }) {
            return nil
        }
        return stripped
    }

    static func redactBreadcrumbData(_ data: [String: Any]?) -> [String: Any]? {
        guard let data else { return nil }
        var redacted: [String: Any] = [:]
        for (key, value) in data {
            let normalizedKey = key.lowercased()
            guard safeBreadcrumbKeys.contains(normalizedKey),
                  !sensitiveKeyFragments.contains(where: { normalizedKey.contains($0) })
            else { continue }

            if normalizedKey == "request_id" {
                if let requestID = redactRequestID(value as? String) {
                    redacted[normalizedKey] = requestID
                }
                continue
            }

            if normalizedKey == "url" {
                if let string = value as? String {
                    redacted[normalizedKey] = stripQuery(from: string)
                }
                continue
            }

            if let number = value as? NSNumber {
                redacted[normalizedKey] = number
            } else if let string = value as? String,
                      let safeString = redactContext(stripQuery(from: string)) {
                redacted[normalizedKey] = safeString
            }
        }
        return redacted.isEmpty ? nil : redacted
    }

    static func redactEventExtra(_ extra: [String: Any]?) -> [String: Any]? {
        redactBreadcrumbData(extra)
    }

    static func isCancellationExceptionType(_ value: String?) -> Bool {
        guard let value else { return false }
        return value == "CancellationError" || value == "NSURLErrorCancelled"
    }

    static func isSensitiveField(_ value: String) -> Bool {
        let normalized = value.lowercased()
        return sensitiveKeyFragments.contains(where: { normalized.contains($0) })
    }

    private static func matches(_ expression: NSRegularExpression, value: String) -> Bool {
        let range = NSRange(value.startIndex..<value.endIndex, in: value)
        return expression.firstMatch(in: value, range: range) != nil
    }
}
