//
//  AppCrashReporting.swift
//  Books & Vocab
//
//  Sentry crash + error reporting bootstrap.
//  No-op until the sentry-cocoa SPM package is added to the project
//  (canImport check) and a SentryDSN value is present in Info.plist.
//
//  Privacy posture:
//  - sendDefaultPii=false → no IP, no default user fields
//  - HTTP breadcrumb URLs have query strings stripped (defense against accidental token-in-URL)
//  - User interaction tracing disabled (a11y labels can carry user content)
//  - Stacktrace attached but frame locals stay on-device (Sentry-cocoa default)
//  - Cancellation noise dropped via beforeSend
//

import Foundation
import os

#if canImport(Sentry)
import Sentry
#endif

enum AppCrashReporting {

    /// Strongly-typed breadcrumb severity. Avoids the silent-fallback risk of
    /// stringly-typed levels (typos like `"err"` previously degraded to `.info`).
    enum BreadcrumbLevel: String {
        case debug
        case info
        case warning
        case error
        case fatal
    }


    private static let logger = Logger(
        subsystem: Bundle.main.bundleIdentifier ?? "com.wordnexus.BooksBrowser",
        category: "CrashReporting"
    )

    /// Call once, as early as possible in the app lifecycle.
    static func bootstrap() {
        #if canImport(Sentry)
        guard let dsn = readDSN(), !dsn.isEmpty else {
            logger.info("Sentry not configured (missing SentryDSN); crash reporting disabled")
            return
        }

        let env = environmentName()
        let release = releaseName()

        SentrySDK.start { options in
            options.dsn = dsn
            options.environment = env
            options.releaseName = release
            if let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String {
                options.dist = build  // disambiguate TestFlight builds sharing one version
            }
            options.attachStacktrace = true
            options.sendDefaultPii = false
            // Performance tracing：release build 0.05 baseline，DEBUG 預設 0。
            // `SENTRY_TRACES_SAMPLE_RATE` env 覆寫（QA / 局部觀測用，介於 0.0–1.0）。
            // 啟用 autoPerformanceTracing 才能讓 SwiftUI / URLSession spans 進 Sentry。
            let tracesRate = Self.resolveTracesSampleRate()
            options.enableAutoPerformanceTracing = tracesRate > 0
            options.tracesSampleRate = NSNumber(value: tracesRate)
            options.maxBreadcrumbs = 100
            options.enableUserInteractionTracing = false  // a11y labels may carry user text
            options.beforeBreadcrumb = { crumb in
                // Strip query strings from HTTP URLs — defense against accidental token-in-URL.
                if crumb.category == "http",
                   let url = crumb.data?["url"] as? String,
                   let qIdx = url.firstIndex(of: "?") {
                    crumb.data?["url"] = String(url[..<qIdx])
                }
                return crumb
            }
            options.beforeSend = { event in
                // Drop cancellation noise to preserve quota for real crashes.
                if let ex = event.exceptions?.first {
                    if ex.type == "CancellationError" || ex.type == "NSURLErrorCancelled" {
                        return nil
                    }
                }
                return event
            }
            #if DEBUG
            options.debug = false
            options.enabled = ProcessInfo.processInfo.environment["SENTRY_ENABLED_IN_DEBUG"] == "1"
            #endif
        }

        logger.info("Sentry initialized env=\(env, privacy: .public) release=\(release ?? "-", privacy: .public)")

        if ProcessInfo.processInfo.arguments.contains("-sentryTest") {
            SentrySDK.capture(message: "Sentry verification: iOS launch-arg test event")
            logger.info("Sentry test event sent via -sentryTest launch arg")
        }
        #endif
    }

    /// Capture a Swift error. Safe to call even when Sentry is inactive.
    /// The optional context tag is scoped to this single event (does not leak to subsequent captures).
    static func record(_ error: Error, context: String? = nil) {
        #if canImport(Sentry)
        SentrySDK.capture(error: error) { scope in
            if let context {
                scope.setTag(value: context, key: "context")
            }
        }
        #else
        _ = error
        _ = context
        #endif
    }

    /// Drop a breadcrumb describing a user action or significant state change.
    /// Safe to call when Sentry is inactive (no-op). Coexists with the
    /// HTTP-URL query-strip filter installed in `bootstrap()`'s `beforeBreadcrumb`.
    ///
    /// - Parameters:
    ///   - category: short bucket tag, e.g. `"audio"`, `"sync"`, `"auth"`.
    ///   - message: human-readable, **never** include PII or auth tokens.
    ///   - level: `.info` (default) / `.warning` / `.error` / `.debug` / `.fatal`.
    ///   - data: optional structured payload, **never** include PII or tokens.
    static func addBreadcrumb(
        category: String,
        message: String,
        level: BreadcrumbLevel = .info,
        data: [String: Any]? = nil
    ) {
        #if canImport(Sentry)
        let crumb = Breadcrumb()
        crumb.category = category
        crumb.message = message
        crumb.level = sentryLevel(from: level)
        if let data { crumb.data = data }
        SentrySDK.addBreadcrumb(crumb)
        #else
        _ = (category, message, level, data)
        #endif
    }

    /// Tag the current user (for filtering in Sentry dashboard).
    /// Pass nil on logout to clear.
    static func setUser(id: String?) {
        #if canImport(Sentry)
        SentrySDK.configureScope { scope in
            if let id {
                let user = User()
                user.userId = id
                scope.setUser(user)
            } else {
                scope.setUser(nil)
            }
        }
        #else
        _ = id
        #endif
    }

    // MARK: - private

    #if canImport(Sentry)
    private static func sentryLevel(from level: BreadcrumbLevel) -> SentryLevel {
        switch level {
        case .debug: return .debug
        case .info: return .info
        case .warning: return .warning
        case .error: return .error
        case .fatal: return .fatal
        }
    }
    #endif

    private static func readDSN() -> String? {
        Bundle.main.object(forInfoDictionaryKey: "SentryDSN") as? String
    }

    private static func environmentName() -> String {
        if let override = Bundle.main.object(forInfoDictionaryKey: "SentryEnvironment") as? String,
           !override.isEmpty {
            return override
        }
        #if DEBUG
        return "debug"
        #else
        return "production"
        #endif
    }

    /// Traces sample rate resolution：
    /// 1. `SENTRY_TRACES_SAMPLE_RATE` env（QA / local override）
    /// 2. Release：0.05（與 backend hot path rate 對齊）
    /// 3. DEBUG：0.0（避免雜訊 + 配額浪費）
    private static func resolveTracesSampleRate() -> Double {
        if let raw = ProcessInfo.processInfo.environment["SENTRY_TRACES_SAMPLE_RATE"],
           let parsed = Double(raw) {
            return min(max(parsed, 0.0), 1.0)
        }
        #if DEBUG
        return 0.0
        #else
        return 0.05
        #endif
    }

    private static func releaseName() -> String? {
        let info = Bundle.main.infoDictionary
        guard
            let short = info?["CFBundleShortVersionString"] as? String,
            let build = info?["CFBundleVersion"] as? String,
            let bundleId = Bundle.main.bundleIdentifier
        else { return nil }
        return "\(bundleId)@\(short)+\(build)"
    }
}
