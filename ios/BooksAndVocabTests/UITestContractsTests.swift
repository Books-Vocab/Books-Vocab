import Foundation
import Testing
@testable import BooksAndVocab

struct UITestContractsTests {
    @Test func inheritedLaunchArgumentsFailClosed() throws {
        #expect(try UITestLaunchArguments.decodeInheritedLaunchArguments(from: nil) == [])
        #expect(throws: UITestLaunchArgumentsError.self) {
            try UITestLaunchArguments.decodeInheritedLaunchArguments(from: "{")
        }
        #expect(throws: UITestLaunchArgumentsError.self) {
            try UITestLaunchArguments.decodeInheritedLaunchArguments(from: "\"not-an-array\"")
        }
        #expect(
            try UITestLaunchArguments.decodeInheritedLaunchArguments(
                from: "[\"-appLaunchProfile\", \"standard\"]"
            ) == ["-appLaunchProfile", "standard"]
        )
    }

    @Test func p11LaunchArgumentsRemainCanonicalAndDistinct() {
        #expect(
            UITestFixtureLaunchContract.vocabularyLibraryP11ReviewMix
                == "-seedFixture:vocabulary:p11.644.reviewMix"
        )
        #expect(
            UITestFixtureLaunchContract.vocabularyLibraryP11MixedRoleCounterexample
                == "-seedFixture:vocabulary:role.mixed"
        )
        #expect(
            UITestFixtureLaunchContract.vocabularyLibraryP11ReviewMix
                != UITestFixtureLaunchContract.vocabularyLibraryFilterRich
        )
    }

    @Test func liveDemoPreflightRequiresExplicitReleasePhysicalRun() throws {
        let fingerprint = String(repeating: "a", count: 64)
        let result = try LiveDemoAccessPreflight(
            environment: [
                LiveDemoAccessPreflight.liveDemoMarkerKey: "1",
                LiveDemoAccessPreflight.accountIdentityFingerprintKey: fingerprint,
            ],
            isReleaseBuild: true,
            isPhysicalDevice: true
        )

        #expect(result.expectedAccountIdentityFingerprint == fingerprint)
        #expect(
            result.matchesAccountIdentifier(
                LiveDemoAccessPreflight.accountIdentityIdentifierPrefix + fingerprint
            )
        )
        #expect(
            !result.matchesAccountIdentifier(
                LiveDemoAccessPreflight.accountIdentityIdentifierPrefix
                    + String(repeating: "b", count: 64)
            )
        )
    }

    @Test func liveDemoPreflightRejectsUnsafeInputs() {
        let fingerprint = String(repeating: "a", count: 64)
        let validEnvironment = [
            LiveDemoAccessPreflight.liveDemoMarkerKey: "1",
            LiveDemoAccessPreflight.accountIdentityFingerprintKey: fingerprint,
        ]

        expectRejected(.debugBuild, environment: validEnvironment, release: false, physical: true)
        expectRejected(.simulator, environment: validEnvironment, release: true, physical: false)
        expectRejected(.missingLiveDemoMarker, environment: [
            LiveDemoAccessPreflight.accountIdentityFingerprintKey: fingerprint,
        ])
        expectRejected(.invalidAccountIdentityFingerprint, environment: [
            LiveDemoAccessPreflight.liveDemoMarkerKey: "1",
            LiveDemoAccessPreflight.accountIdentityFingerprintKey: "not-a-sha256",
        ])
        expectRejected(.fixtureDataset, environment: validEnvironment.merging([
            "KG_FIXTURE_DATASET_DEFLATE_B64": "fixture",
        ]) { _, new in new })
        expectRejected(.fixtureLaunchArgument, environment: validEnvironment.merging([
            "KG_UI_TEST_APP_ARGS_JSON": "[\"-seedFixture:auth:signedIn\"]",
        ]) { _, new in new })
        expectRejected(.backendOverride, environment: validEnvironment.merging([
            "KG_UI_TEST_SERVER_URL": "https://staging.example.invalid",
        ]) { _, new in new })
    }

    private func expectRejected(
        _ expected: LiveDemoAccessPreflightError,
        environment: [String: String],
        release: Bool = true,
        physical: Bool = true
    ) {
        #expect(throws: expected) {
            try LiveDemoAccessPreflight(
                environment: environment,
                isReleaseBuild: release,
                isPhysicalDevice: physical
            )
        }
    }
}
