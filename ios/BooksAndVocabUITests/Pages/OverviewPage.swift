import XCTest

/// Page Object for the Overview (Stats) tab.
struct OverviewPage {
    let app: XCUIApplication

    // MARK: - Content

    /// Rendered stats dashboard (only present when the summary computed from
    /// synced entries + review records is non-empty — i.e. real content phase,
    /// not loading / empty / logged-out.
    var statsContent: XCUIElement {
        exactlyOne(app.descendants(matching: .any)["overview.statsContent"], "overview.statsContent")
    }

    /// Calendar entry point. This deliberately uses the stable identifier
    /// rather than the localized section title.
    var reviewCalendarButton: XCUIElement {
        exactlyOne(app.buttons["reviewCalendar.open"], "reviewCalendar.open")
    }

    // MARK: - Assertions

    func assertIsActive(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        // Overview has a NavigationStack with a large title in both logged-in and logged-out states.
        let navBar = exactlyOne(app.navigationBars, "overview navigation bar", file: file, line: line)
        navBar.assertExists(timeout: 3, file: file, line: line)
    }
}

/// Page Object for Review Calendar. All selectors are identifiers owned by
/// the app surface; no localized labels are used for navigation or assertions.
struct ReviewCalendarPage {
    let app: XCUIApplication

    var monthHeader: XCUIElement {
        exactlyOne(app.staticTexts["reviewCalendar.monthHeader"], "reviewCalendar.monthHeader")
    }

    var previousMonthButton: XCUIElement {
        exactlyOne(app.buttons["reviewCalendar.previousMonth"], "reviewCalendar.previousMonth")
    }

    var nextMonthButton: XCUIElement {
        exactlyOne(app.buttons["reviewCalendar.nextMonth"], "reviewCalendar.nextMonth")
    }

    var selectedDay: XCUIElement {
        exactlyOne(app.buttons["reviewCalendar.selectedDay"], "reviewCalendar.selectedDay")
    }

    var emptyDayDetail: XCUIElement {
        exactlyOne(app.descendants(matching: .any)["reviewCalendar.emptyDayDetail"], "reviewCalendar.emptyDayDetail")
    }

    var populatedDayDetail: XCUIElement {
        exactlyOne(app.descendants(matching: .any)["reviewCalendar.populatedDayDetail"], "reviewCalendar.populatedDayDetail")
    }

    var populatedDaySummary: XCUIElement {
        exactlyOne(app.staticTexts["reviewCalendar.populatedDaySummary"], "reviewCalendar.populatedDaySummary")
    }

    func day(_ key: String) -> XCUIElement {
        exactlyOne(app.buttons["reviewCalendar.day.\(key)"], "reviewCalendar.day.\(key)")
    }
}

private func exactlyOne(
    _ query: XCUIElementQuery,
    _ label: String,
    file: StaticString = #filePath,
    line: UInt = UInt(#line)
) -> XCUIElement {
    XCTAssertEqual(
        query.count,
        1,
        "\(label) must resolve exactly one element; duplicates are invalid",
        file: file,
        line: line
    )
    return query.element(boundBy: 0)
}
