import XCTest

/// Page Object for the Overview (Stats) tab.
struct OverviewPage {
    let app: XCUIApplication

    // MARK: - Content

    /// Rendered stats dashboard (only present when the summary computed from
    /// synced entries + review records is non-empty — i.e. real content phase,
    /// not loading / empty / logged-out).
    var statsContent: XCUIElement {
        app.descendants(matching: .any)["overview.statsContent"].firstMatch
    }

    /// Calendar entry point. This deliberately uses the stable identifier
    /// rather than the localized section title.
    var reviewCalendarButton: XCUIElement {
        app.buttons["reviewCalendar.open"].firstMatch
    }

    // MARK: - Assertions

    func assertIsActive(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        // Overview has a NavigationStack with a large title in both logged-in and logged-out states.
        let navBar = app.navigationBars.firstMatch
        navBar.assertExists(timeout: 3, file: file, line: line)
    }
}

/// Page Object for Review Calendar. All selectors are identifiers owned by
/// the app surface; no localized labels are used for navigation or assertions.
struct ReviewCalendarPage {
    let app: XCUIApplication

    var monthHeader: XCUIElement {
        app.staticTexts["reviewCalendar.monthHeader"].firstMatch
    }

    var previousMonthButton: XCUIElement {
        app.buttons["reviewCalendar.previousMonth"].firstMatch
    }

    var nextMonthButton: XCUIElement {
        app.buttons["reviewCalendar.nextMonth"].firstMatch
    }

    var selectedDay: XCUIElement {
        app.buttons["reviewCalendar.selectedDay"].firstMatch
    }

    var emptyDayDetail: XCUIElement {
        app.descendants(matching: .any)["reviewCalendar.emptyDayDetail"].firstMatch
    }

    var populatedDayDetail: XCUIElement {
        app.descendants(matching: .any)["reviewCalendar.populatedDayDetail"].firstMatch
    }

    func day(_ key: String) -> XCUIElement {
        app.buttons["reviewCalendar.day.\(key)"].firstMatch
    }
}
