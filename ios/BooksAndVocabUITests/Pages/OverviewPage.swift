import XCTest

/// Page Object for the Overview (Stats) tab.
struct OverviewPage {
    let app: XCUIApplication

    private func elements(identifier: String) -> XCUIElementQuery {
        app.descendants(matching: .any).matching(identifier: identifier)
    }

    private func element(identifier: String) -> XCUIElement {
        elements(identifier: identifier).element(boundBy: 0)
    }

    // MARK: - Content

    /// Rendered stats dashboard (only present when the summary computed from
    /// synced entries + review records is non-empty — i.e. real content phase,
    /// not loading / empty / logged-out.
    var statsContent: XCUIElement {
        exactlyOne(
            app.descendants(matching: .any).matching(identifier: "overview.statsContent"),
            "overview.statsContent"
        )
    }

    /// Calendar entry point. This deliberately uses the stable identifier
    /// rather than the localized section title.
    var reviewCalendarButton: XCUIElement {
        exactlyOne(app.buttons.matching(identifier: "reviewCalendar.open"), "reviewCalendar.open")
    }

    var overview: XCUIElement { element(identifier: "overview") }
    var calendar: XCUIElement { element(identifier: "calendar") }
    var forecast: XCUIElement { element(identifier: "overview.forecast") }
    var forecastCard: XCUIElement { element(identifier: "overview.forecast.card") }

    func metric(_ name: String) -> XCUIElement {
        element(identifier: "overview.metric.\(name)")
    }

    private func forecastBucketQuery(_ dayKey: String) -> XCUIElementQuery {
        forecastCard
            .descendants(matching: .any)
            .matching(identifier: "forecast.bucket.\(dayKey)")
    }

    func forecastBucket(
        _ dayKey: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> XCUIElement {
        let query = forecastBucketQuery(dayKey)
        XCTAssertEqual(
            query.count,
            1,
            "forecast.bucket.\(dayKey) must resolve to exactly one live AX element",
            file: file,
            line: line
        )
        return query.firstMatch
    }

    func assertOverviewAccessibilityHierarchy(
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        let overviewQuery = elements(identifier: "overview")
        overview.assertExists(timeout: 10, file: file, line: line)
        XCTAssertEqual(overviewQuery.count, 1, "overview must be a unique live AX ancestor", file: file, line: line)
    }

    func assertUniqueForecastContract(
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        for (identifier, element) in [
            ("overview.forecast", forecast),
            ("overview.forecast.card", forecastCard),
        ] {
            XCTAssertEqual(elements(identifier: identifier).count, 1, "\(identifier) must be unique", file: file, line: line)
            element.assertExists(timeout: 10, file: file, line: line)
        }

        let bucketQuery = forecastCard
            .descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH[c] %@", "forecast.bucket."))
        XCTAssertGreaterThan(bucketQuery.count, 0, "forecast must expose at least one bucket", file: file, line: line)
        for bucket in bucketQuery.allElementsBoundByIndex {
            XCTAssertEqual(
                elements(identifier: bucket.identifier).count,
                1,
                "\(bucket.identifier) must be globally unique",
                file: file,
                line: line
            )
        }
    }

    func assertForecastContainsCount(
        _ count: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        let buckets = forecastCard
            .descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH[c] %@", "forecast.bucket."))
            .allElementsBoundByIndex
        XCTAssertTrue(
            buckets.contains { ($0.value as? String)?.contains(count) == true },
            "forecast must expose a bucket with count \(count)",
            file: file,
            line: line
        )
    }

    func assertMetric(_ name: String, value: String, file: StaticString = #filePath, line: UInt = UInt(#line)) {
        let query = elements(identifier: "overview.metric.\(name)")
        let element = metric(name)
        element.assertExists(timeout: 10, file: file, line: line)
        XCTAssertEqual(query.count, 1, "overview.metric.\(name) must be globally unique", file: file, line: line)
        XCTAssertEqual(
            overview.descendants(matching: .any).matching(identifier: "overview.metric.\(name)").count,
            1,
            "overview.metric.\(name) must be a live descendant of overview",
            file: file,
            line: line
        )
        XCTAssertEqual(element.value as? String, value, file: file, line: line)
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
        // SwiftUI may materialize the identifier-bearing Text as `Other`
        // inside the calendar composition; the identifier is the stable
        // contract, not the UIKit-backed accessibility type.
        exactlyOne(
            app.descendants(matching: .any).matching(identifier: "reviewCalendar.monthHeader"),
            "reviewCalendar.monthHeader"
        )
    }

    var previousMonthButton: XCUIElement {
        exactlyOne(app.buttons.matching(identifier: "reviewCalendar.previousMonth"), "reviewCalendar.previousMonth")
    }

    var nextMonthButton: XCUIElement {
        exactlyOne(app.buttons.matching(identifier: "reviewCalendar.nextMonth"), "reviewCalendar.nextMonth")
    }

    var selectedDay: XCUIElement {
        exactlyOne(app.buttons.matching(identifier: "reviewCalendar.selectedDay"), "reviewCalendar.selectedDay")
    }

    var emptyDayDetail: XCUIElement {
        exactlyOne(
            app.descendants(matching: .any).matching(identifier: "reviewCalendar.emptyDayDetail"),
            "reviewCalendar.emptyDayDetail"
        )
    }

    var emptyDaySummary: XCUIElement {
        exactlyOne(app.staticTexts.matching(identifier: "reviewCalendar.emptyDaySummary"), "reviewCalendar.emptyDaySummary")
    }

    var populatedDayDetail: XCUIElement {
        exactlyOne(
            app.descendants(matching: .any).matching(identifier: "reviewCalendar.populatedDayDetail"),
            "reviewCalendar.populatedDayDetail"
        )
    }

    var populatedDaySummary: XCUIElement {
        exactlyOne(app.staticTexts.matching(identifier: "reviewCalendar.populatedDaySummary"), "reviewCalendar.populatedDaySummary")
    }

    var installedFixtureProof: XCUIElement {
        exactlyOne(
            app.descendants(matching: .any).matching(identifier: "reviewCalendar.installedFixture"),
            "reviewCalendar.installedFixture"
        )
    }

    var runtimeGeometry: XCUIElement {
        exactlyOne(
            app.descendants(matching: .any).matching(identifier: "reviewCalendar.runtimeGeometry"),
            "reviewCalendar.runtimeGeometry"
        )
    }

    func day(_ key: String) -> XCUIElement {
        exactlyOne(
            app.buttons.matching(identifier: "reviewCalendar.day.\(key)"),
            "reviewCalendar.day.\(key)"
        )
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
