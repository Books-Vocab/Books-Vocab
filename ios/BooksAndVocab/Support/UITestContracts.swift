import Foundation

public enum UITestLaunchArgumentsError: Error, CustomStringConvertible {
    case missingUTF8
    case invalidJSON(underlying: Error)

    public var description: String {
        switch self {
        case .missingUTF8:
            return "KG_UI_TEST_APP_ARGS_JSON is not valid UTF-8"
        case .invalidJSON(let underlying):
            return "KG_UI_TEST_APP_ARGS_JSON must be a JSON array of strings: \(underlying)"
        }
    }
}

public enum UITestLaunchArguments {
    public static func decodeInheritedLaunchArguments(from raw: String?) throws -> [String] {
        guard let raw else {
            return []
        }
        guard let data = raw.data(using: .utf8) else {
            throw UITestLaunchArgumentsError.missingUTF8
        }
        do {
            return try JSONDecoder().decode([String].self, from: data)
        } catch {
            throw UITestLaunchArgumentsError.invalidJSON(underlying: error)
        }
    }
}

public enum UITestFixtureLaunchContract {
    public static let vocabularyLibraryFilterRich = "-seedFixture:vocabulary:vocabListFilterRich"
    public static let vocabularyLibraryP11ReviewMix = "-seedFixture:vocabulary:p11.644.reviewMix"
}

public enum LiveDemoAccessPreflightError: String, Error, Equatable {
    case debugBuild
    case simulator
    case missingLiveDemoMarker
    case invalidAccountIdentityFingerprint
    case fixtureDataset
    case fixtureLaunchArgument
    case backendOverride
}

public struct LiveDemoAccessPreflight {
    public static let liveDemoMarkerKey = "KG_LIVE_DEMO_RUN"
    public static let accountIdentityFingerprintKey = "KG_LIVE_DEMO_ACCOUNT_IDENTITY_SHA256"
    public static let accountIdentityIdentifierPrefix = "settings.account.identity."

    public let expectedAccountIdentityFingerprint: String

    public init(
        environment: [String: String],
        isReleaseBuild: Bool,
        isPhysicalDevice: Bool
    ) throws {
        guard isReleaseBuild else {
            throw LiveDemoAccessPreflightError.debugBuild
        }
        guard isPhysicalDevice else {
            throw LiveDemoAccessPreflightError.simulator
        }
        guard environment[Self.liveDemoMarkerKey] == "1" else {
            throw LiveDemoAccessPreflightError.missingLiveDemoMarker
        }
        guard let fingerprint = environment[Self.accountIdentityFingerprintKey],
              fingerprint.range(
                of: "^[0-9a-f]{64}$",
                options: .regularExpression
              ) != nil else {
            throw LiveDemoAccessPreflightError.invalidAccountIdentityFingerprint
        }
        guard environment["KG_FIXTURE_DATASET_B64"] == nil,
              environment["KG_FIXTURE_DATASET_DEFLATE_B64"] == nil else {
            throw LiveDemoAccessPreflightError.fixtureDataset
        }
        guard environment["KG_UI_TEST_SERVER_URL"] == nil else {
            throw LiveDemoAccessPreflightError.backendOverride
        }

        if let rawArguments = environment["KG_UI_TEST_APP_ARGS_JSON"] {
            guard let data = rawArguments.data(using: .utf8),
                  let arguments = try? JSONDecoder().decode([String].self, from: data),
                  !arguments.contains(where: Self.isFixtureArgument) else {
                throw LiveDemoAccessPreflightError.fixtureLaunchArgument
            }
        }

        expectedAccountIdentityFingerprint = fingerprint
    }

    public func matchesAccountIdentifier(_ identifier: String) -> Bool {
        identifier
            == Self.accountIdentityIdentifierPrefix + expectedAccountIdentityFingerprint
    }

    private static func isFixtureArgument(_ argument: String) -> Bool {
        argument.hasPrefix("-seedFixture:")
            || argument == "-isolatedAuthSession"
            || argument == "-resetContainer"
            || argument == "-catalog"
            || argument == "ui-smoke"
    }
}
