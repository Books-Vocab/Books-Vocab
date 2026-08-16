import Foundation
import BooksAndVocab
import XCTest

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
        proofElement.scrollIntoView()

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
