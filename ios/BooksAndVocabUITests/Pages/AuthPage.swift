import XCTest

/// Page Object for the auth surfaces: the LoginSheet, the bookshelf guest
/// entry point, and the Settings account section (logged-in vs guest panel).
struct AuthPage {
    let app: XCUIApplication

    // MARK: - LoginSheet (presented by login gates app-wide)

    var loginSheet: XCUIElement {
        app.descendants(matching: .any)["auth.loginSheet"]
    }

    var loginSheetGoogleButton: XCUIElement {
        app.buttons["auth.loginSheet.googleButton"]
    }

    var loginSheetAppleButton: XCUIElement {
        app.buttons["auth.loginSheet.appleButton"]
    }

    var loginSheetCancelButton: XCUIElement {
        app.buttons["auth.loginSheet.cancelButton"]
    }

    // MARK: - Guest entry points

    /// Bookshelf empty-state "登入帳號" button (guest only).
    var bookshelfLoginEntry: XCUIElement {
        app.buttons["bookshelf.emptyState.loginButton"]
    }

    // MARK: - Settings account section

    /// Guest panel: marketing hero + Google/Apple login buttons.
    var settingsLoginPanel: XCUIElement {
        app.descendants(matching: .any)["settings.account.loginView"]
    }

    /// Logged-in panel: account summary + logout.
    var settingsLoggedInPanel: XCUIElement {
        app.descendants(matching: .any)["settings.account.loggedInView"]
    }

    var settingsLogoutButton: XCUIElement {
        app.buttons["settings.account.logoutButton"]
    }

    // MARK: - Actions

    /// Dismiss the LoginSheet via its cancel button.
    @discardableResult
    func cancelLoginSheet(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        loginSheetCancelButton.tapWhenReady(file: file, line: line)
        return self
    }

    // MARK: - Assertions

    /// The gate actually fired: the sheet is on screen with real SSO entries.
    func assertLoginSheetPresented(
        timeout: TimeInterval = 5,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        XCTAssertTrue(
            loginSheet.waitUntilExists(timeout: timeout),
            "LoginSheet (auth.loginSheet) 未出現 — 登入閘門沒有觸發",
            file: file, line: line
        )
        XCTAssertTrue(
            loginSheetGoogleButton.waitUntilExists(timeout: 2),
            "LoginSheet 缺 Google 登入按鈕",
            file: file, line: line
        )
        XCTAssertTrue(
            loginSheetAppleButton.exists,
            "LoginSheet 缺 Apple 登入按鈕",
            file: file, line: line
        )
    }

    func assertLoginSheetGone(
        timeout: TimeInterval = 5,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        XCTAssertTrue(
            loginSheet.waitUntilGone(timeout: timeout),
            "LoginSheet 應已關閉但仍在畫面上",
            file: file, line: line
        )
    }
}
