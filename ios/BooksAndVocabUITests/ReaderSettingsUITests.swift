import XCTest

final class ReaderSettingsUITests: UITestCase {
    override func setUpWithError() throws {
        try super.setUpWithError()
        executionTimeAllowance = 150
    }

    @MainActor
    func testReaderSettingsWorldOverlayRoundTripsThroughPreviewAndReaderLocalReset() throws {
        let app = launchIsolatedApp(
            fixtures: [.readerRealBookLibrary],
            perfLog: "reader-settings"
        )
        captureStep("launch", app: app)

        let bookshelf = AppPage(app: app).goToBookshelf()
        guard bookshelf.anyBookCard.waitUntilExists(timeout: 10) else {
            XCTFail("Reader UI World must materialize a book before settings can be opened")
            return
        }
        bookshelf.anyBookCard.tapWhenReady()

        let reader = ReaderPage(app: app)
        guard reader.contentText("Introduction").waitUntilExists(timeout: 45) else {
            XCTFail("Reader UI World must render the seeded book content")
            return
        }
        reader.openSettings()

        XCTAssertTrue(reader.settingsPreview.waitUntilExists(timeout: 5))
        XCTAssertTrue(reader.lineHeightSlider.waitUntilExists(timeout: 5))
        guard let initialLineHeight = reader.lineHeightValue() else {
            XCTFail("line-height slider must expose a numeric accessibility value")
            return
        }
        XCTAssertEqual(initialLineHeight, 2.1, accuracy: 0.05)

        let previewHeight = reader.settingsPreview.frame.height
        reader.lineHeightSlider.adjust(toNormalizedSliderPosition: 0)
        XCTAssertTrue(
            reader.lineHeightSlider.waitUntilValueEquals("1", timeout: 3),
            "line-height slider must expose the lower contract bound"
        )
        XCTAssertEqual(
            reader.settingsPreview.frame.height,
            previewHeight,
            accuracy: 1,
            "preview viewport height must not move when line-height changes"
        )

        reader.resetReaderSettings()
        XCTAssertTrue(
            reader.lineHeightSlider.waitUntilValueEquals("1.4", timeout: 3),
            "Reader-local reset must restore the Reader default line-height"
        )
        XCTAssertTrue(reader.settingsPreview.exists)
    }

    @MainActor
    func testReaderPreviewKeepsViewportAcrossDarkAndSepiaCounterexamples() throws {
        let app = launchIsolatedApp(
            fixtures: [.readerRealBookLibrary],
            perfLog: "reader-settings-themes"
        )
        let bookshelf = AppPage(app: app).goToBookshelf()
        guard bookshelf.anyBookCard.waitUntilExists(timeout: 10) else {
            XCTFail("Reader UI World must materialize a book before settings can be opened")
            return
        }
        bookshelf.anyBookCard.tapWhenReady()

        let reader = ReaderPage(app: app)
        guard reader.contentText("Introduction").waitUntilExists(timeout: 45) else {
            XCTFail("Reader UI World must render the seeded book content")
            return
        }
        reader.openSettings()

        guard reader.settingsPreview.waitUntilExists(timeout: 5),
              reader.showPreview()
        else {
            XCTFail("Reader settings preview must be visible before theme counterexamples")
            return
        }
        let viewportHeight = reader.settingsPreview.frame.height

        for theme in ["dark", "sepia"] {
            guard reader.selectTheme(theme) else {
                XCTFail("Reader theme option must expose a hittable stable selector: \(theme)")
                return
            }
            guard reader.showPreview() else {
                XCTFail("Reader preview must remain reachable after selecting theme: \(theme)")
                return
            }
            captureStep("\(theme)-theme", app: app)
            XCTAssertEqual(
                reader.settingsPreview.frame.height,
                viewportHeight,
                accuracy: 1,
                "\(theme) preview must keep the bounded viewport geometry"
            )
        }
    }

    @MainActor
    func testReaderPreviewKeepsViewportUnderAccessibilityDynamicType() throws {
        let app = launchIsolatedApp(
            extraArgs: [
                "-UIPreferredContentSizeCategory",
                "UICTContentSizeCategoryAccessibilityExtraExtraExtraLarge"
            ],
            fixtures: [.readerRealBookLibrary],
            perfLog: "reader-settings-dynamic-type"
        )
        let bookshelf = AppPage(app: app).goToBookshelf()
        guard bookshelf.anyBookCard.waitUntilExists(timeout: 10) else {
            XCTFail("Reader UI World must materialize a book before settings can be opened")
            return
        }
        bookshelf.anyBookCard.tapWhenReady()

        let reader = ReaderPage(app: app)
        guard reader.contentText("Introduction").waitUntilExists(timeout: 45) else {
            XCTFail("Reader UI World must render the seeded book content")
            return
        }
        reader.openSettings()

        guard reader.settingsPreview.waitUntilExists(timeout: 5),
              reader.lineHeightSlider.waitUntilExists(timeout: 5),
              reader.settingsDoneButton.waitUntilExists(timeout: 5)
        else {
            XCTFail("Reader settings selectors must remain reachable at Accessibility Dynamic Type")
            return
        }
        guard reader.showPreview() else {
            XCTFail("Reader preview must remain reachable at Accessibility Dynamic Type")
            return
        }
        captureStep("dynamic-type", app: app)
        let viewportHeight = reader.settingsPreview.frame.height

        reader.lineHeightSlider.adjust(toNormalizedSliderPosition: 1)
        XCTAssertEqual(
            reader.settingsPreview.frame.height,
            viewportHeight,
            accuracy: 1,
            "Dynamic Type must not make line-height changes resize the preview viewport"
        )
    }
}
