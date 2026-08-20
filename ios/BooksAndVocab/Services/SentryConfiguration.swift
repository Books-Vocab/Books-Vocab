//
//  SentryConfiguration.swift
//  Books & Vocab
//
//  Pure configuration seam for the crash reporter. Keeping environment and
//  bundle reads here makes the SDK adapter small and keeps release/privacy
//  behavior unit-testable without starting Sentry.
//

import Foundation

struct SentryConfiguration: Equatable {
    let dsn: String?
    let environment: String
    let releaseName: String?
    let dist: String?
    let tracesSampleRate: Double
    let enabled: Bool
    let debugBuild: Bool
    let testEventRequested: Bool

    static func current() -> SentryConfiguration {
        #if DEBUG
        let debugBuild = true
        #else
        let debugBuild = false
        #endif

        return make(
            infoDictionary: Bundle.main.infoDictionary ?? [:],
            bundleIdentifier: Bundle.main.bundleIdentifier,
            environment: ProcessInfo.processInfo.environment,
            arguments: ProcessInfo.processInfo.arguments,
            debugBuild: debugBuild
        )
    }

    static func make(
        infoDictionary: [String: Any],
        bundleIdentifier: String?,
        environment: [String: String],
        arguments: [String],
        debugBuild: Bool
    ) -> SentryConfiguration {
        let dsn = nonEmptyString(infoDictionary["SentryDSN"])
        let testEventRequested = arguments.contains("-sentryTest")
        let environmentName = nonEmptyString(infoDictionary["SentryEnvironment"])
            ?? (debugBuild ? "debug" : "production")
        let marketingVersion = nonEmptyString(infoDictionary["CFBundleShortVersionString"])
        let build = nonEmptyString(infoDictionary["CFBundleVersion"])
        let releaseName: String?
        if let bundleIdentifier = nonEmptyString(bundleIdentifier),
           let marketingVersion,
           let build {
            releaseName = "\(bundleIdentifier)@\(marketingVersion)+\(build)"
        } else {
            releaseName = nil
        }

        let tracesSampleRate = resolveTracesSampleRate(
            rawOverride: environment["SENTRY_TRACES_SAMPLE_RATE"],
            debugBuild: debugBuild
        )
        let explicitlyEnabled = environment["SENTRY_ENABLED_IN_DEBUG"] == "1"
        let enabled = !debugBuild || explicitlyEnabled || testEventRequested

        return SentryConfiguration(
            dsn: dsn,
            environment: environmentName,
            releaseName: releaseName,
            dist: build,
            tracesSampleRate: tracesSampleRate,
            enabled: enabled,
            debugBuild: debugBuild,
            testEventRequested: testEventRequested
        )
    }

    static func resolveTracesSampleRate(rawOverride: String?, debugBuild: Bool) -> Double {
        if let rawOverride,
           let parsed = Double(rawOverride),
           parsed.isFinite {
            return min(max(parsed, 0.0), 1.0)
        }
        return debugBuild ? 0.0 : 0.05
    }

    private static func nonEmptyString(_ value: Any?) -> String? {
        guard let value = value as? String else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
