//
//  AppCrashReporting.swift
//  BooksBrowser
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
            options.enableAutoPerformanceTracing = false
            options.tracesSampleRate = 0.0
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
