//
//  AppDiagnosticContext.swift
//  Books & Vocab
//
//  Small, bounded local diagnostic buffer. It is intentionally independent
//  from product analytics and is the future source for a user support report.
//

import Foundation

struct AppDiagnosticSnapshot: Equatable, Sendable {
    let observations: [String]
    let requestIDs: [String]
    let latestSentryEventID: String?
}

final class AppDiagnosticContext: @unchecked Sendable {
    static let shared = AppDiagnosticContext()

    private let lock = NSLock()
    private let maxObservations: Int
    private let maxRequestIDs: Int
    private var observations: [String] = []
    private var requestIDs: [String] = []
    private var latestSentryEventID: String?

    init(maxObservations: Int = 20, maxRequestIDs: Int = 20) {
        self.maxObservations = max(1, maxObservations)
        self.maxRequestIDs = max(1, maxRequestIDs)
    }

    func recordObservation(message: String, requestID: String? = nil) {
        let redactedMessage = SentryPrivacyPolicy.redactBreadcrumbMessage(message) ?? "redacted"
        let redactedRequestID = SentryPrivacyPolicy.redactRequestID(requestID)
        lock.lock()
        defer { lock.unlock() }
        observations.append(redactedMessage)
        if observations.count > maxObservations {
            observations.removeFirst(observations.count - maxObservations)
        }
        appendRequestID(redactedRequestID)
    }

    func recordError(
        errorType: String,
        context: String?,
        requestID: String?,
        eventID: String?
    ) {
        let safeType = SentryPrivacyPolicy.redactContext(errorType) ?? "Error"
        let safeContext = SentryPrivacyPolicy.redactContext(context)
        let message = [safeContext, safeType].compactMap { $0 }.joined(separator: " ")
        recordObservation(message: message, requestID: requestID)
        recordEventID(eventID)
    }

    func recordEventID(_ eventID: String?) {
        guard let eventID = SentryPrivacyPolicy.redactOpaqueID(eventID) else { return }
        lock.lock()
        latestSentryEventID = eventID
        lock.unlock()
    }

    func snapshot() -> AppDiagnosticSnapshot {
        lock.lock()
        defer { lock.unlock() }
        return AppDiagnosticSnapshot(
            observations: observations,
            requestIDs: requestIDs,
            latestSentryEventID: latestSentryEventID
        )
    }

    #if DEBUG
    func resetForTesting() {
        lock.lock()
        observations.removeAll(keepingCapacity: true)
        requestIDs.removeAll(keepingCapacity: true)
        latestSentryEventID = nil
        lock.unlock()
    }
    #endif

    private func appendRequestID(_ requestID: String?) {
        guard let requestID, !requestIDs.contains(requestID) else { return }
        requestIDs.append(requestID)
        if requestIDs.count > maxRequestIDs {
            requestIDs.removeFirst(requestIDs.count - maxRequestIDs)
        }
    }
}
