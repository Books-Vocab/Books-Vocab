#if os(iOS)
import Foundation
import SwiftData

/// Bridges the canonical UI World fixture document into the live SwiftData
/// container used by simulator UI tests. Physical-device fixture writes are
/// rejected by the container and asset helpers.
enum UITestFixtureSeedValidationError: Error, Equatable {
    case persistentContainer
}

@MainActor
enum UITestFixtureSeed {
    static var statsProjectionClock: StatsProjectionClock?

    /// Parse `-seedFixture:<domain>:<id>` arguments and inject matching fixtures.
    static func injectIfNeeded(into container: ModelContainer, arguments: [String]) {
        guard AppRuntimeOptions.isUITesting(arguments: arguments) else { return }

        do {
            try validateContainerForFixtureSeeding(container)
        } catch {
            failFixtureSeed(
                "UITestFixtureSeed: refused — container has persistent store(s); fixtures may only seed the ephemeral UI-testing container"
            )
        }

        let readerRuntimeSelection = ReaderRuntimeFixtureAdapter.selection(
            arguments: arguments,
            dataset: FixtureDatasetStore.readerProvenance()
        )
        if arguments.contains(where: { $0.hasPrefix("-readerRuntimeScenario:") }),
           readerRuntimeSelection == nil {
            failFixtureSeed("Unknown Reader runtime scenario argument")
        }

        applyPreferencesFromWorld()

        for arg in arguments {
            guard arg.hasPrefix("-seedFixture:") else { continue }
            let remainder = arg.dropFirst("-seedFixture:".count)
            let parts = remainder.split(separator: ":", maxSplits: 1).map(String.init)
            guard parts.count == 2 else {
                failFixtureSeed("Malformed UI-test fixture argument: \(arg)")
            }
            let domain = parts[0]
            let id = parts[1]

            switch domain {
            case "bookshelf":
                seedBookshelf(id, into: container)
            case "podcast":
                seedPodcast(id, into: container)
            case "todayReview":
                seedTodayReview(id, into: container)
            case "auth":
                seedAuth(id, into: container)
            case "settings":
                seedSettings(id, into: container)
            case "shell":
                seedShell(id, into: container)
            case "search":
                seedSearch(id, into: container)
            case "vocabulary":
                seedVocabulary(id, into: container)
            case "reader":
                seedReader(id, into: container, runtime: readerRuntimeSelection)
            case "notebook":
                seedNotebook(id, into: container)
            case "dictionary":
                seedDictionary(id)
#if DEBUG && targetEnvironment(simulator)
            case "explore":
                seedExplore(id, into: container)
#endif
            case "vocabulary":
                seedVocabulary(id, into: container)
            case "entitlements":
                guard id == "pro" || id == "free" else {
                    failFixtureSeed("Unknown entitlements fixture ID: \(id)")
                }
            default:
                failFixtureSeed("Unknown UI-test fixture domain: \(domain)")
            }
        }
    }

    static func validateContainerForFixtureSeeding(_ container: ModelContainer) throws {
        guard !container.configurations.isEmpty,
              container.configurations.allSatisfy(\.isStoredInMemoryOnly) else {
            throw UITestFixtureSeedValidationError.persistentContainer
        }
    }

    /// Dictionary content is canonical scenarioContext data; the seed only
    /// verifies that the declared fixture resolves to the injected dataset.
    /// Dictionary data is already canonical scenarioContext content. The
    /// launch seed only resolves the declared surface row; it never writes a
    /// synthetic dictionary response into SwiftData.
    private static func seedDictionary(_ id: String) {
        guard let fixtureID = UIWorldDictionaryFixtureID(rawValue: id) else {
            failFixtureSeed("Unknown dictionary fixture ID: \(id)")
        }
        guard FixtureDatasetStore.dictionarySeed(for: fixtureID) != nil else {
            failFixtureSeed(
                FixtureDatasetStore.seedResolutionFailureDescription(
                    resolving: "dictionary.\(fixtureID.rawValue)"
                )
            )
        }
        AppLog.app.info("UITestFixtureSeed: resolved canonical dictionary fixture \(fixtureID.rawValue)")
    }

    static func failFixtureSeed(_ message: String) -> Never {
        AppLog.app.error("\(message)")
        preconditionFailure(message)
    }

    @MainActor
    private static func applyPreferencesFromWorld() {
        let document = FixtureDatasetStore.requireDocument()
        guard !document.preferences.isEmpty else { return }
#if targetEnvironment(simulator)
        document.preferences.apply()
        // The overlay can be written after SwiftUI has already initialized
        // ReaderSettings.shared. Rehydrate the live observable instance so
        // controls and the real Readium reader consume the same UI World.
        ReaderSettings.shared.reloadFromPersistence()
#else
        preconditionFailure("UI World preferences are simulator-only; refusing to overwrite real UserDefaults/iCloud KVS on device")
#endif
    }

    /// The no-label overload is used by auth/podcast/search fixtures and keeps
    /// the isolated-session guard required by the real UserDefaults/Keychain
    /// safety contract.
    @MainActor
    @discardableResult
    static func seedSignedInLoginFromWorld(
        arguments: [String] = ProcessInfo.processInfo.arguments,
        auth: AuthManager? = nil
    ) -> Bool {
#if targetEnvironment(simulator)
        guard AppRuntimeOptions.shouldUseIsolatedAuthSession(arguments: arguments) else {
            if AppRuntimeOptions.isUITesting(arguments: arguments) {
                preconditionFailure("auth.signedIn fixture requires -isolatedAuthSession (use launchIsolatedApp)")
            }
            AppLog.app.error("UITestFixtureSeed: refused auth.signedIn without -isolatedAuthSession — fake session would persist into the real store")
            return false
        }
        applyAuthSeed(.signedIn, auth: auth ?? AuthManager.shared)
        return true
#else
        AppLog.app.error("UITestFixtureSeed: refused fixture login on physical device — would overwrite the real Keychain session")
        preconditionFailure("auth.signedIn fixture is simulator-only")
#endif
    }

    /// Settings fixtures may select a distinct auth seed, while still running
    /// inside the already-isolated simulator UI-test session.
    @MainActor
    static func seedSignedInLoginFromWorld(using fixtureID: UIWorldAuthFixtureID = .signedIn) {
#if targetEnvironment(simulator)
        applyAuthSeed(fixtureID, auth: AuthManager.shared)
#else
        AppLog.app.error("UITestFixtureSeed: refused fixture login on physical device — would overwrite the real Keychain session")
        preconditionFailure("auth.signedIn fixture is simulator-only")
#endif
    }

#if targetEnvironment(simulator)
    @MainActor
    private static func applyAuthSeed(_ fixtureID: UIWorldAuthFixtureID, auth: AuthManager) {
        let seed = FixtureDatasetStore.requireAuthSeed(for: fixtureID)
        guard seed.isLoggedIn else {
            preconditionFailure("\(fixtureID.rawValue) fixture requires a logged-in auth seed")
        }
        let userId = seed.userId ?? ""
        guard !userId.isEmpty else {
            preconditionFailure("\(fixtureID.rawValue) fixture requires non-empty userId")
        }
        auth.displayName = seed.displayName ?? ""
        auth.userEmail = seed.email
        switch seed.keychainTokenState {
        case .available:
            let token = seed.token ?? ""
            guard !token.isEmpty else {
                preconditionFailure("\(fixtureID.rawValue) keychainTokenState=available requires non-empty token")
            }
            auth.login(userId: userId, token: token)
        case .readFailed:
            auth.applyUITestPersistedSession(PersistedAuthSession(
                userId: userId,
                displayName: seed.displayName,
                userEmail: seed.email,
                avatarURL: nil,
                token: nil,
                keychainReadFailed: true
            ))
        case .absent:
            preconditionFailure("\(fixtureID.rawValue) cannot declare keychainTokenState=absent")
        }
    }
#endif
}
#endif
