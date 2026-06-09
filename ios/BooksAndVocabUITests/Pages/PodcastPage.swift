import XCTest

/// Page Object for the Podcast Home tab.
struct PodcastPage {
    let app: XCUIApplication

    // MARK: - Content

    /// Series card: `accessibilityIdentifier = "podcast.series.<seriesId>"`
    func seriesCard(id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: "podcast.series.\(id)").firstMatch
    }

    /// Any series card (fallback when IDs are unknown).
    var anySeriesCard: XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH[c] %@", "podcast.series."))
            .firstMatch
    }

    var followToggle: XCUIElement {
        app.buttons["podcast.followToggle"]
    }

    // MARK: - Episode List (inside a series detail)

    var episodeListStaleBanner: XCUIElement {
        app.staticTexts["podcast.episodeList.staleBanner"]
    }

    // MARK: - Player

    var playerSettingsButton: XCUIElement {
        app.buttons["podcast.player.settingsButton"]
    }

    // MARK: - Actions

    @discardableResult
    func tapFirstSeries(file: StaticString = #filePath, line: UInt = #line) -> Self {
        anySeriesCard.tapWhenReady(file: file, line: line)
        return self
    }

    // MARK: - Assertions

    func assertIsActive(file: StaticString = #filePath, line: UInt = #line) {
        anySeriesCard.assertExists(timeout: 5, file: file, line: line)
    }
}
