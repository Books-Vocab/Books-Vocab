import Foundation
import XCTest

private enum LiveDemoAccessPreflightError: String, Error {
    case debugBuild
    case simulator
    case missingLiveDemoMarker
    case invalidAccountIdentityFingerprint
    case fixtureDataset
    case fixtureLaunchArgument
    case backendOverride
}

private struct LiveDemoAccessPreflight {
    static let liveDemoMarkerKey = "KG_LIVE_DEMO_RUN"
    static let accountIdentityFingerprintKey = "KG_LIVE_DEMO_ACCOUNT_IDENTITY_SHA256"
    static let accountIdentityIdentifierPrefix = "settings.account.identity."

    let expectedAccountIdentityFingerprint: String

    init(
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

    func matchesAccountIdentifier(_ identifier: String) -> Bool {
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

/// Exact-device App Review probe. It verifies the persisted live session's
/// normalized account identity and backend-sourced Pro entitlement. Credential
/// freshness remains a separate, root-bound human attestation because the SSO
/// provider credential flow is not safely automatable without exposing secrets.
final class LiveDemoAccessUITests: UITestCase {
    @MainActor
    func testLiveDemoAccountHasProEntitlement() throws {
        let environment = ProcessInfo.processInfo.environment
        let preflight: LiveDemoAccessPreflight
        do {
            preflight = try LiveDemoAccessPreflight(
                environment: environment,
                isReleaseBuild: Self.isReleaseBuild,
                isPhysicalDevice: Self.isPhysicalDevice
            )
        } catch let error as LiveDemoAccessPreflightError {
            XCTFail("Live demo preflight rejected the run: \(error.rawValue)")
            return
        }

        // Deliberately do not register this app with UITestCase.currentApp:
        // failure diagnostics include the full accessibility tree, which would
        // copy the visible account email into logs. Evidence uses the cropped
        // Pro-card attachment below instead.
        let app = makeConfiguredApp()
        app.launch()

        let bookshelf = AppPage(app: app).goToBookshelf()
        XCTAssertTrue(app.waitForNavigationToSettle())
        _ = bookshelf.tapSettings()

        let auth = AuthPage(app: app)
        let isLoggedIn = auth.settingsLoggedInPanel.waitUntilExists(timeout: 15)

        let actualIdentity = app.descendants(matching: .any)
            .matching(NSPredicate(
                format: "identifier BEGINSWITH %@",
                LiveDemoAccessPreflight.accountIdentityIdentifierPrefix
            ))
            .firstMatch
        let identityExists = actualIdentity.waitUntilExists(timeout: 5)
        let identityMatches = identityExists
            && preflight.matchesAccountIdentifier(actualIdentity.identifier)

        let activePro = app.descendants(matching: .any)["settings.subscription.pro.active"]
        let inactivePro = app.descendants(matching: .any)["settings.subscription.pro.inactive"]
        let hasActivePro = activePro.waitUntilExists(timeout: 20)

        // Move the raw account identity off-screen before any assertion can
        // trigger an XCTest failure screenshot. The kept proof is cropped to
        // the entitlement card and therefore contains no account identifier.
        let proofElement = hasActivePro ? activePro : inactivePro
        if proofElement.exists {
            proofElement.scrollIntoView()
        } else {
            app.swipeUp()
        }

        XCTAssertTrue(isLoggedIn, "Live demo device is not signed in")
        XCTAssertTrue(identityExists, "Live demo account identity is unavailable")
        XCTAssertTrue(identityMatches, "Live demo device is signed in to the wrong account")
        XCTAssertTrue(hasActivePro, "Live demo account does not expose Pro entitlement")
        XCTAssertFalse(inactivePro.exists, "Live demo account exposes the Free entitlement state")

        let attachment = XCTAttachment(screenshot: activePro.screenshot())
        attachment.name = "Step 01-live-demo-account-pro"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private static var isReleaseBuild: Bool {
#if DEBUG
        false
#else
        true
#endif
    }

    private static var isPhysicalDevice: Bool {
#if targetEnvironment(simulator)
        false
#else
        true
#endif
    }
}

final class LiveDemoAccessPreflightTests: XCTestCase {
    private let fingerprint = String(repeating: "a", count: 64)

    func testAcceptsOnlyExplicitReleasePhysicalLiveRun() throws {
        let result = try LiveDemoAccessPreflight(
            environment: [
                LiveDemoAccessPreflight.liveDemoMarkerKey: "1",
                LiveDemoAccessPreflight.accountIdentityFingerprintKey: fingerprint,
            ],
            isReleaseBuild: true,
            isPhysicalDevice: true
        )

        XCTAssertEqual(result.expectedAccountIdentityFingerprint, fingerprint)
        XCTAssertTrue(
            result.matchesAccountIdentifier(
                LiveDemoAccessPreflight.accountIdentityIdentifierPrefix + fingerprint
            )
        )
        XCTAssertFalse(
            result.matchesAccountIdentifier(
                LiveDemoAccessPreflight.accountIdentityIdentifierPrefix
                    + String(repeating: "b", count: 64)
            )
        )
    }

    func testRejectsDebugSimulatorFixtureBackendAndWrongAccountContract() {
        assertRejected(.debugBuild, environment: validEnvironment, release: false, physical: true)
        assertRejected(.simulator, environment: validEnvironment, release: true, physical: false)
        assertRejected(.missingLiveDemoMarker, environment: [
            LiveDemoAccessPreflight.accountIdentityFingerprintKey: fingerprint,
        ])
        assertRejected(.invalidAccountIdentityFingerprint, environment: [
            LiveDemoAccessPreflight.liveDemoMarkerKey: "1",
            LiveDemoAccessPreflight.accountIdentityFingerprintKey: "not-a-sha256",
        ])
        assertRejected(.fixtureDataset, environment: validEnvironment.merging([
            "KG_FIXTURE_DATASET_DEFLATE_B64": "fixture",
        ]) { _, new in new })
        assertRejected(.fixtureLaunchArgument, environment: validEnvironment.merging([
            "KG_UI_TEST_APP_ARGS_JSON": "[\"-seedFixture:auth:signedIn\"]",
        ]) { _, new in new })
        assertRejected(.backendOverride, environment: validEnvironment.merging([
            "KG_UI_TEST_SERVER_URL": "https://staging.example.invalid",
        ]) { _, new in new })
    }

    private var validEnvironment: [String: String] {
        [
            LiveDemoAccessPreflight.liveDemoMarkerKey: "1",
            LiveDemoAccessPreflight.accountIdentityFingerprintKey: fingerprint,
        ]
    }

    private func assertRejected(
        _ expected: LiveDemoAccessPreflightError,
        environment: [String: String],
        release: Bool = true,
        physical: Bool = true,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertThrowsError(
            try LiveDemoAccessPreflight(
                environment: environment,
                isReleaseBuild: release,
                isPhysicalDevice: physical
            ),
            file: file,
            line: line
        ) { error in
            XCTAssertEqual(error as? LiveDemoAccessPreflightError, expected, file: file, line: line)
        }
    }
}
