//
//  AppAnalytics.swift
//  Books & Vocab
//
//  輕量可觀測性基礎設施：結構化事件追蹤 + OSSignposter 延遲度量
//  所有資料透過 os.Logger 輸出，可在 Console.app / Instruments 中篩選
//

import Foundation
import os

// MARK: - Analytics Events

enum AnalyticsEvent {

    // — Translation —
    case translationRequested(word: String, type: TranslationType)
    case translationCompleted(word: String, type: TranslationType, latencyMs: Int)
    case translationFailed(word: String, type: TranslationType, error: String)

    // — Sync —
    case syncStarted
    case syncStepCompleted(step: String, durationMs: Int, success: Bool)
    case syncCompleted(durationMs: Int, outcome: SyncOutcome)

    // — Review —
    case reviewSessionStarted(cardCount: Int)
    case reviewCardSubmitted(feedback: String, cardIndex: Int, totalCards: Int)
    case reviewSessionEnded(remembered: Int, forgot: Int, completed: Bool, durationMs: Int)

    // — Auth —
    case loginCompleted(provider: String)
    case loginFailed(provider: String, error: String)
    case logoutPerformed(reason: String)
    case accountSwitchDetected

    // — App Lifecycle —
    case appSessionStarted
    case appEnteredBackground
    case backgroundSyncTriggered
    case backgroundSyncCompleted(durationMs: Int, success: Bool)

    enum TranslationType: String {
        case quick
        case phrase
        case explanation
    }

    enum SyncOutcome: String {
        case success
        case partial
        case failed
        case cancelled
    }
}

// MARK: - Signpost Names (for Instruments)

extension OSSignpostID {
    static func from(_ name: StaticString) -> OSSignpostID {
        OSSignpostID(log: AppAnalytics.signpostLog)
    }
}

// MARK: - Analytics Service

enum AppAnalytics {

    static let logger = Logger(
        subsystem: Bundle.main.bundleIdentifier ?? "com.wordnexus.BooksBrowser",
        category: "Analytics"
    )

    static let signpostLog = OSLog(
        subsystem: Bundle.main.bundleIdentifier ?? "com.wordnexus.BooksBrowser",
        category: .pointsOfInterest
    )

    private static let signposter = OSSignposter(logHandle: signpostLog)

    private static func redactedTextSummary(_ text: String) -> String {
        "chars=\(text.count)"
    }

    static func recordObservation(
        level: AppObservationLevel,
        category: String = "analytics",
        message: String
    ) {
        AppObservationStore.shared.record(level: level, category: category, message: message)
    }

    // MARK: - Track Event

    static func track(_ event: AnalyticsEvent) {
        switch event {

        // — Translation —
        case .translationRequested(let word, let type):
            recordObservation(
                level: .info,
                message: "event=translation_requested word=\(redactedTextSummary(word)) type=\(type.rawValue)"
            )
            logger.info("event=translation_requested word=\(word, privacy: .private(mask: .hash)) type=\(type.rawValue, privacy: .public)")

        case .translationCompleted(let word, let type, let latencyMs):
            recordObservation(
                level: .info,
                message: "event=translation_completed word=\(redactedTextSummary(word)) type=\(type.rawValue) latency_ms=\(latencyMs)"
            )
            logger.info("event=translation_completed word=\(word, privacy: .private(mask: .hash)) type=\(type.rawValue, privacy: .public) latency_ms=\(latencyMs)")

        case .translationFailed(let word, let type, let error):
            recordObservation(
                level: .warning,
                message: "event=translation_failed word=\(redactedTextSummary(word)) type=\(type.rawValue) error=redacted"
            )
            logger.warning("event=translation_failed word=\(word, privacy: .private(mask: .hash)) type=\(type.rawValue, privacy: .public) error=\(error, privacy: .private(mask: .hash))")

        // — Sync —
        case .syncStarted:
            recordObservation(level: .info, message: "event=sync_started")
            logger.info("event=sync_started")

        case .syncStepCompleted(let step, let durationMs, let success):
            recordObservation(
                level: .info,
                message: "event=sync_step_completed step=\(step) duration_ms=\(durationMs) success=\(success)"
            )
            logger.info("event=sync_step_completed step=\(step, privacy: .public) duration_ms=\(durationMs) success=\(success)")

        case .syncCompleted(let durationMs, let outcome):
            recordObservation(
                level: .info,
                message: "event=sync_completed duration_ms=\(durationMs) outcome=\(outcome.rawValue)"
            )
            logger.info("event=sync_completed duration_ms=\(durationMs) outcome=\(outcome.rawValue, privacy: .public)")

        // — Review —
        case .reviewSessionStarted(let cardCount):
            recordObservation(level: .info, message: "event=review_session_started card_count=\(cardCount)")
            logger.info("event=review_session_started card_count=\(cardCount)")

        case .reviewCardSubmitted(let feedback, let cardIndex, let totalCards):
            recordObservation(
                level: .info,
                message: "event=review_card_submitted feedback=\(feedback) index=\(cardIndex) total=\(totalCards)"
            )
            logger.info("event=review_card_submitted feedback=\(feedback, privacy: .public) index=\(cardIndex) total=\(totalCards)")

        case .reviewSessionEnded(let remembered, let forgot, let completed, let durationMs):
            recordObservation(
                level: .info,
                message: "event=review_session_ended remembered=\(remembered) forgot=\(forgot) completed=\(completed) duration_ms=\(durationMs)"
            )
            logger.info("event=review_session_ended remembered=\(remembered) forgot=\(forgot) completed=\(completed) duration_ms=\(durationMs)")

        // — Auth —
        case .loginCompleted(let provider):
            recordObservation(level: .info, message: "event=login_completed provider=\(provider)")
            logger.info("event=login_completed provider=\(provider, privacy: .public)")

        case .loginFailed(let provider, let error):
            recordObservation(level: .warning, message: "event=login_failed provider=\(provider) error=redacted")
            logger.warning("event=login_failed provider=\(provider, privacy: .public) error=\(error, privacy: .private(mask: .hash))")

        case .logoutPerformed(let reason):
            recordObservation(level: .info, message: "event=logout_performed reason=\(reason)")
            logger.info("event=logout_performed reason=\(reason, privacy: .public)")

        case .accountSwitchDetected:
            recordObservation(level: .info, message: "event=account_switch_detected")
            logger.info("event=account_switch_detected")

        // — App Lifecycle —
        case .appSessionStarted:
            recordObservation(level: .info, message: "event=app_session_started")
            logger.info("event=app_session_started")

        case .appEnteredBackground:
            recordObservation(level: .info, message: "event=app_entered_background")
            logger.info("event=app_entered_background")

        case .backgroundSyncTriggered:
            recordObservation(level: .info, message: "event=background_sync_triggered")
            logger.info("event=background_sync_triggered")

        case .backgroundSyncCompleted(let durationMs, let success):
            recordObservation(
                level: .info,
                message: "event=background_sync_completed duration_ms=\(durationMs) success=\(success)"
            )
            logger.info("event=background_sync_completed duration_ms=\(durationMs) success=\(success)")
        }

        SessionMetrics.shared.record(event)
    }

    // MARK: - Signpost Helpers (for Instruments Time Profiler)

    static func beginInterval(_ name: StaticString) -> OSSignpostIntervalState {
        signposter.beginInterval(name)
    }

    static func endInterval(_ name: StaticString, _ state: OSSignpostIntervalState) {
        signposter.endInterval(name, state)
    }
}

// MARK: - Session Metrics (in-memory aggregates)

final class SessionMetrics: @unchecked Sendable {
    static let shared = SessionMetrics()

    private let lock = NSLock()
    private var _translationCount = 0
    private var _translationFailures = 0
    private var _translationTotalLatencyMs = 0
    private var _syncCount = 0
    private var _syncFailures = 0
    private var _reviewCardsTotal = 0
    private var _reviewRemembered = 0
    private var _reviewForgot = 0
    private var _reviewSessionsCompleted = 0
    private var _reviewSessionsAbandoned = 0

    private init() {}

    func record(_ event: AnalyticsEvent) {
        lock.lock()
        defer { lock.unlock() }

        switch event {
        case .translationCompleted(_, _, let latencyMs):
            _translationCount += 1
            _translationTotalLatencyMs += latencyMs
        case .translationFailed:
            _translationCount += 1
            _translationFailures += 1
        case .syncCompleted(_, let outcome):
            _syncCount += 1
            if outcome != .success { _syncFailures += 1 }
        case .reviewCardSubmitted(let feedback, _, _):
            _reviewCardsTotal += 1
            if feedback == "remembered" { _reviewRemembered += 1 }
            else { _reviewForgot += 1 }
        case .reviewSessionEnded(_, _, let completed, _):
            if completed { _reviewSessionsCompleted += 1 }
            else { _reviewSessionsAbandoned += 1 }
        default:
            break
        }
    }

    /// Snapshot for logging on app background
    func snapshot() -> SessionSnapshot {
        lock.lock()
        defer { lock.unlock() }
        return SessionSnapshot(
            translationCount: _translationCount,
            translationFailures: _translationFailures,
            translationAvgLatencyMs: _translationCount > 0
                ? _translationTotalLatencyMs / _translationCount : 0,
            syncCount: _syncCount,
            syncFailures: _syncFailures,
            reviewCardsTotal: _reviewCardsTotal,
            reviewRemembered: _reviewRemembered,
            reviewForgot: _reviewForgot,
            reviewSessionsCompleted: _reviewSessionsCompleted,
            reviewSessionsAbandoned: _reviewSessionsAbandoned
        )
    }

    func reset() {
        lock.lock()
        defer { lock.unlock() }
        _translationCount = 0
        _translationFailures = 0
        _translationTotalLatencyMs = 0
        _syncCount = 0
        _syncFailures = 0
        _reviewCardsTotal = 0
        _reviewRemembered = 0
        _reviewForgot = 0
        _reviewSessionsCompleted = 0
        _reviewSessionsAbandoned = 0
    }
}

struct SessionSnapshot {
    let translationCount: Int
    let translationFailures: Int
    let translationAvgLatencyMs: Int
    let syncCount: Int
    let syncFailures: Int
    let reviewCardsTotal: Int
    let reviewRemembered: Int
    let reviewForgot: Int
    let reviewSessionsCompleted: Int
    let reviewSessionsAbandoned: Int

    func logSummary() {
        guard translationCount > 0 || syncCount > 0 || reviewCardsTotal > 0 else { return }
        let message = """
            event=session_summary \
            translations=\(translationCount) \
            translation_failures=\(translationFailures) \
            translation_avg_ms=\(translationAvgLatencyMs) \
            syncs=\(syncCount) \
            sync_failures=\(syncFailures) \
            review_cards=\(reviewCardsTotal) \
            review_remembered=\(reviewRemembered) \
            review_forgot=\(reviewForgot) \
            review_sessions_completed=\(reviewSessionsCompleted) \
            review_sessions_abandoned=\(reviewSessionsAbandoned)
            """
        AppAnalytics.recordObservation(level: .info, message: message)
        AppAnalytics.logger.info("""
            event=session_summary \
            translations=\(translationCount) \
            translation_failures=\(translationFailures) \
            translation_avg_ms=\(translationAvgLatencyMs) \
            syncs=\(syncCount) \
            sync_failures=\(syncFailures) \
            review_cards=\(reviewCardsTotal) \
            review_remembered=\(reviewRemembered) \
            review_forgot=\(reviewForgot) \
            review_sessions_completed=\(reviewSessionsCompleted) \
            review_sessions_abandoned=\(reviewSessionsAbandoned)
            """)
    }
}
