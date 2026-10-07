import StoreKit
import Testing
@testable import BooksAndVocab

struct SentryConfigurationTests {
    private let info: [String: Any] = [
        "SentryDSN": "https://public@example.invalid/1",
        "SentryEnvironment": "qa",
        "CFBundleShortVersionString": "2.0.1",
        "CFBundleVersion": "10"
    ]

    @Test func releaseConfigurationKeepsReleaseAndDistContract() {
        let configuration = SentryConfiguration.make(
            infoDictionary: info,
            bundleIdentifier: "com.example.books",
            environment: [:],
            arguments: [],
            debugBuild: false
        )

        #expect(configuration.dsn == "https://public@example.invalid/1")
        #expect(configuration.environment == "qa")
        #expect(configuration.releaseName == "com.example.books@2.0.1+10")
        #expect(configuration.dist == "10")
        #expect(configuration.tracesSampleRate == 0.05)
        #expect(configuration.enabled)
        #expect(!configuration.testEventRequested)
    }

    @Test func debugBuildStaysDisabledUnlessExplicitlyEnabled() {
        let disabled = SentryConfiguration.make(
            infoDictionary: info,
            bundleIdentifier: "com.example.books",
            environment: [:],
            arguments: [],
            debugBuild: true
        )
        let envEnabled = SentryConfiguration.make(
            infoDictionary: info,
            bundleIdentifier: "com.example.books",
            environment: ["SENTRY_ENABLED_IN_DEBUG": "1"],
            arguments: [],
            debugBuild: true
        )
        let testEnabled = SentryConfiguration.make(
            infoDictionary: info,
            bundleIdentifier: "com.example.books",
            environment: [:],
            arguments: ["-sentryTest"],
            debugBuild: true
        )

        #expect(!disabled.enabled)
        #expect(disabled.tracesSampleRate == 0)
        #expect(envEnabled.enabled)
        #expect(testEnabled.enabled)
        #expect(testEnabled.testEventRequested)
    }

    @Test func traceRateOverrideIsClampedAndInvalidValuesUseDefault() {
        #expect(SentryConfiguration.resolveTracesSampleRate(rawOverride: "1.5", debugBuild: true) == 1)
        #expect(SentryConfiguration.resolveTracesSampleRate(rawOverride: "-0.5", debugBuild: false) == 0)
        #expect(SentryConfiguration.resolveTracesSampleRate(rawOverride: "not-a-rate", debugBuild: false) == 0.05)
        #expect(SentryConfiguration.resolveTracesSampleRate(rawOverride: "nan", debugBuild: false) == 0.05)
    }

    @Test func missingBundleFieldsDoNotInventReleaseIdentity() {
        let configuration = SentryConfiguration.make(
            infoDictionary: ["SentryDSN": "dsn"],
            bundleIdentifier: nil,
            environment: [:],
            arguments: [],
            debugBuild: false
        )

        #expect(configuration.releaseName == nil)
        #expect(configuration.dist == nil)
    }

    @Test func bootstrapEnvironmentIsSynchronousAndOnlyUnoverriddenReleaseRefinesAtRuntime() {
        var withoutOverride = info
        withoutOverride.removeValue(forKey: "SentryEnvironment")

        func configuration(
            _ info: [String: Any],
            debugBuild: Bool,
            cachedChannel: String? = nil
        ) -> SentryConfiguration {
            SentryConfiguration.make(
                infoDictionary: info,
                bundleIdentifier: "com.example.books",
                environment: [:],
                arguments: [],
                debugBuild: debugBuild,
                cachedVerifiedChannel: cachedChannel
            )
        }

        let firstLaunchRelease = configuration(withoutOverride, debugBuild: false)
        let cachedTestFlight = configuration(withoutOverride, debugBuild: false, cachedChannel: "testflight")
        let cachedProduction = configuration(withoutOverride, debugBuild: false, cachedChannel: "production")
        let cachedGarbage = configuration(withoutOverride, debugBuild: false, cachedChannel: "qa-tampered")
        let debug = configuration(withoutOverride, debugBuild: true, cachedChannel: "testflight")
        let overridden = configuration(info, debugBuild: false, cachedChannel: "testflight")

        // Known gap: the first launch after install reports production until
        // the async AppTransaction lookup resolves and persists the channel.
        #expect(firstLaunchRelease.environment == "production")
        #expect(firstLaunchRelease.refinesEnvironmentAtRuntime)
        #expect(cachedTestFlight.environment == "testflight")
        #expect(cachedTestFlight.refinesEnvironmentAtRuntime)
        #expect(cachedProduction.environment == "production")
        #expect(cachedGarbage.environment == "production")
        #expect(debug.environment == "debug")
        #expect(!debug.refinesEnvironmentAtRuntime)
        #expect(overridden.environment == "qa")
        #expect(!overridden.refinesEnvironmentAtRuntime)
    }

    @Test func onlyVerifiedStoreEnvironmentsProduceAChannelToPersist() {
        #expect(SentryConfiguration.verifiedChannel(for: .sandbox) == "testflight")
        #expect(SentryConfiguration.verifiedChannel(for: .production) == "production")
        // Xcode StoreKit testing is not a distribution channel; errors and
        // unverified results arrive as nil. Neither touches the cache.
        #expect(SentryConfiguration.verifiedChannel(for: .xcode) == nil)
        #expect(SentryConfiguration.verifiedChannel(for: nil) == nil)
    }
}
