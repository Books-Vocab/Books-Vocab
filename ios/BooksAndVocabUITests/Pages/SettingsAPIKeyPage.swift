import XCTest

struct SettingsAPIKeyPage {
    let app: XCUIApplication

    private func exact(_ type: XCUIElement.ElementType, _ identifier: String) -> XCUIElement {
        app.descendants(matching: type)
            .matching(identifier: identifier)
            .element
    }

    var scrollView: XCUIElement {
        exact(.scrollView, "settings.apiKeys.scrollView")
    }

    var proRequired: XCUIElement {
        exact(.other, "settings.apiKeys.proRequired")
    }

    var createButton: XCUIElement {
        exact(.button, "settings.apiKeys.createButton")
    }

    var createForm: XCUIElement {
        exact(.other, "settings.apiKeys.createForm")
    }

    var labelField: XCUIElement {
        exact(.textField, "settings.apiKeys.labelField")
    }

    var confirmCreateButton: XCUIElement {
        exact(.button, "settings.apiKeys.confirmCreateButton")
    }

    var newSecret: XCUIElement {
        exact(.other, "settings.apiKeys.newSecret")
    }

    var plaintext: XCUIElement {
        exact(.staticText, "settings.apiKeys.plaintext")
    }

    var copyButton: XCUIElement {
        exact(.button, "settings.apiKeys.copyButton")
    }

    var error: XCUIElement {
        exact(.other, "settings.apiKeys.error")
    }

    func assertIsPresented(
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        XCTAssertTrue(
            scrollView.waitUntilExists(timeout: 10),
            "API key management page must expose its production scroll view",
            file: file,
            line: line
        )
        XCTAssertFalse(scrollView.frame.isEmpty, file: file, line: line)
    }
}

extension SettingsSheetPage {
    var apiKeyManagementRow: XCUIElement {
        app.buttons["settings.account.apiKeyManagement"]
    }

    @discardableResult
    func openAPIKeyManagement(
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> SettingsAPIKeyPage {
        XCTAssertTrue(
            apiKeyManagementRow.waitUntilHittable(timeout: 10),
            "Pro account must expose a hittable external API key management row",
            file: file,
            line: line
        )
        apiKeyManagementRow.tapWhenReady(file: file, line: line)
        return SettingsAPIKeyPage(app: app)
    }
}
