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

    var anyEpisodeRow: XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH[c] %@", "podcast.episode."))
            .firstMatch
    }

    /// Episode row by full AX identifier (e.g. `PodcastFixture.episode2RowID`).
    func episodeRow(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    // MARK: - Player

    var playerSettingsButton: XCUIElement {
        app.buttons["podcast.player.settingsButton"]
    }

    var playPauseButton: XCUIElement {
        app.buttons["podcast.player.playPauseButton"]
    }

    var pauseButton: XCUIElement {
        app.buttons["podcast.player.pauseButton"]
    }

    var elapsedTimeLabel: XCUIElement {
        app.staticTexts["podcast.player.elapsedTime"]
    }

    var durationTimeLabel: XCUIElement {
        app.staticTexts["podcast.player.durationTime"]
    }

    var seekBar: XCUIElement {
        app.otherElements["podcast.player.seekBar"]
    }

    var loginSheet: XCUIElement {
        app.descendants(matching: .any)["auth.loginSheet"]
    }

    var playerLoginGate: XCUIElement {
        app.descendants(matching: .any)["podcast.player.locked.loginGate"]
    }

    var playerLoginButton: XCUIElement {
        app.buttons["podcast.player.locked.signInButton"]
    }

    // MARK: - Actions

    @discardableResult
    func tapFirstSeries(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        anySeriesCard.tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func tapFirstEpisode(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        anyEpisodeRow.tapWhenReady(file: file, line: line)
        return self
    }

    // MARK: - Assertions

    func assertIsActive(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        anySeriesCard.assertExists(timeout: 5, file: file, line: line)
    }
}
