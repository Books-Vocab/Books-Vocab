//
//  SentryConfiguration.swift
//  Books & Vocab
//
//  Pure configuration seam for the crash reporter. Keeping environment and
//  bundle reads here makes the SDK adapter small and keeps release/privacy
//  behavior unit-testable without starting Sentry.
//

import Foundation
import StoreKit

struct SentryConfiguration: Equatable {
    let dsn: String?
    let environment: String
    let releaseName: String?
    let dist: String?
    let tracesSampleRate: Double
    let enabled: Bool
    let debugBuild: Bool
    let testEventRequested: Bool
    /// Release build without a `SentryEnvironment` override: the bootstrap
    /// value is provisional and refined asynchronously from StoreKit.
    let refinesEnvironmentAtRuntime: Bool

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
            debugBuild: debugBuild,
            cachedVerifiedChannel: UserDefaults.standard.string(forKey: verifiedChannelDefaultsKey)
        )
    }

    static func make(
        infoDictionary: [String: Any],
        bundleIdentifier: String?,
        environment: [String: String],
        arguments: [String],
        debugBuild: Bool,
        cachedVerifiedChannel: String? = nil
    ) -> SentryConfiguration {
        let dsn = nonEmptyString(infoDictionary["SentryDSN"])
        let testEventRequested = arguments.contains("-sentryTest")
        let environmentOverride = nonEmptyString(infoDictionary["SentryEnvironment"])
        let environmentName = bootstrapEnvironment(
            override: environmentOverride,
            debugBuild: debugBuild,
            cachedVerifiedChannel: cachedVerifiedChannel
        )
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
            testEventRequested: testEventRequested,
            refinesEnvironmentAtRuntime: !debugBuild && environmentOverride == nil
        )
    }

    /// Persisted result of the last *verified* AppTransaction lookup.
    static let verifiedChannelDefaultsKey = "kg.sentry.verifiedDistributionChannel"
    private static let distributionChannels: Set<String> = ["testflight", "production"]

    /// Synchronous environment used at SDK start, so even startup crashes are
    /// tagged. TestFlight and App Store ship the same Release binary; the
    /// channel comes from the last verified AppTransaction persisted by the
    /// previous launch. Known gap: the first launch after install reports
    /// `production` until the async lookup resolves.
    static func bootstrapEnvironment(
        override: String?,
        debugBuild: Bool,
        cachedVerifiedChannel: String?
    ) -> String {
        if let override { return override }
        if debugBuild { return "debug" }
        if let cachedVerifiedChannel, distributionChannels.contains(cachedVerifiedChannel) {
            return cachedVerifiedChannel
        }
        return "production"
    }

    /// Channel implied by a verified StoreKit 2 AppTransaction environment:
    /// sandbox = TestFlight, production = App Store. Xcode StoreKit testing,
    /// unverified results and lookup errors (nil) yield no channel, so
    /// neither the cache nor the live scope is touched.
    /// Known caveat: a Release build installed directly from Xcode/devices
    /// (not App Store) also reports `.sandbox`, so it is tagged `testflight`
    /// and cannot be told apart from real TestFlight builds by this tag.
    static func verifiedChannel(for environment: AppStore.Environment?) -> String? {
        switch environment {
        case .sandbox?: return "testflight"
        case .production?: return "production"
        default: return nil
        }
    }

    static func storeVerifiedChannel(_ channel: String) {
        UserDefaults.standard.set(channel, forKey: verifiedChannelDefaultsKey)
    }

    /// Verified AppTransaction environment, or nil on error/unverified.
    static func fetchAppTransactionEnvironment() async -> AppStore.Environment? {
        do {
            guard case .verified(let transaction) = try await AppTransaction.shared else { return nil }
            return transaction.environment
        } catch {
            return nil
        }
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
