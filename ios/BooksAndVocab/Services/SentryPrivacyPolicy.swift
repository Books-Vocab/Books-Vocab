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
    private static let labelPattern = try! NSRegularExpression(pattern: "^[A-Za-z0-9._:+_/-]{1,128}$")
    private static let messagePattern = try! NSRegularExpression(pattern: "^[a-z0-9][a-z0-9._/-]*(?: [a-z0-9][a-z0-9._/-]*){0,7}$")
    private static let safeAPIRoots: Set<String> = [
        "auth", "books", "billing", "decks", "dictionary", "graph", "health", "library",
        "notebooks", "pipeline", "podcasts", "system", "translate", "user", "vocab"
    ]
    private static let safeBreadcrumbKeys: Set<String> = [
        "attempt", "duration_ms", "error_type", "feature", "format", "method", "operation",
        "phase", "provider", "request_id", "result", "retry_count", "status_code", "url",
        "url_error_code", "source"
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
        let stripped = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !stripped.isEmpty, stripped.count <= 160 else { return nil }
        let parts = stripped.split(separator: " ", maxSplits: 1).map(String.init)
        if parts.count == 2, ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"].contains(parts[0]) {
            guard let endpoint = redactBreadcrumbURL(parts[1]) else { return nil }
            return "\(parts[0]) \(endpoint)"
        }
        let lowercased = stripped.lowercased()
        if sensitiveKeyFragments.contains(where: { lowercased.contains($0) }) {
            return nil
        }
        guard matches(messagePattern, value: stripped) else { return nil }
        return stripped
    }

    /// Keep only an allowlisted API resource root. Dynamic IDs, book titles,
    /// hosts, userinfo, query strings and fragments never cross this boundary.
    static func redactBreadcrumbURL(_ value: String?) -> String? {
        guard let value else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !trimmed.contains(where: { $0.isWhitespace }) else { return nil }
        guard let components = URLComponents(string: trimmed),
              components.user == nil,
              components.password == nil
        else { return nil }

        let path: String
        if components.scheme != nil || components.host != nil {
            path = components.path
        } else {
            path = stripQuery(from: trimmed).split(separator: "#", maxSplits: 1).first.map(String.init) ?? ""
        }
        let decodedPath = path.removingPercentEncoding ?? path
        let segments = decodedPath.split(separator: "/").map(String.init)
        guard segments.count >= 2,
              segments[0].lowercased() == "api",
              safeAPIRoots.contains(segments[1].lowercased())
        else { return nil }
        return "/api/\(segments[1].lowercased())"
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
                    if let endpoint = redactBreadcrumbURL(string) {
                        redacted[normalizedKey] = endpoint
                    }
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
        isCancellationException(type: value, value: nil)
    }

    static func isCancellationException(type: String?, value: String?) -> Bool {
        let typeText = type?.lowercased() ?? ""
        let valueText = value?.lowercased() ?? ""
        let combined = "\(typeText) \(valueText)"
        if typeText == "cancellationerror"
            || typeText.hasSuffix(".cancellationerror")
            || typeText == "nsurlerrorcancelled"
            || typeText == "urlerror.cancelled" {
            return true
        }
        // NSError bridging commonly produces an `NSError` exception whose
        // value contains the domain and code, rather than the symbolic
        // NSURLErrorCancelled name.
        return combined.contains("nsurlerrordomain")
            && (combined.contains("-999") || combined.contains("cancel"))
    }

    static func redactExceptionType(_ value: String?) -> String? {
        guard let safe = redactContext(value) else { return nil }
        let validSuffixes = ["Error", "Exception", "Failure", "Crash", "Fault"]
        guard safe == "Crash"
            || safe == "Exception"
            || validSuffixes.contains(where: { safe.hasSuffix($0) }) else {
            return nil
        }
        return safe
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
