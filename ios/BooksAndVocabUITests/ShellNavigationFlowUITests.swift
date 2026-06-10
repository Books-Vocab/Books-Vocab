//
//  ShellNavigationFlowUITests.swift
//  Books & Vocab UI Tests
//
//  Shell/Tab navigation flow with REAL seeded data + visual evidence,
//  following the PodcastPlaybackPerfUITests model (docs/sop/ui_flow_evidence.md).
//
//  Supersedes ShellSmokeUITests while preserving its coverage intent:
//    - all tabs visible on launch
//    - every tab can be entered, gets selected, keeps the tab bar alive
//    - navigation chrome present on each section
//  …and upgrades the assertions from "tab bar reacted" to "the target tab's
//  real content actually rendered" (book card / podcast series card / notebook
//  card / overview stats), plus cross-tab navigation-stack preservation.
//

import XCTest

final class ShellNavigationFlowUITests: UITestCase {
    private let shellNotebookId = "ui-shell-notebook"

    @MainActor
    func testTabSwitchingRendersRealContentAndPreservesState() throws {
        let app = launchIsolatedApp(
            fixtures: [
                .bookshelf("with_books_library"),
                .podcastPlayablePreview,
                .shellNavigation
            ],
            perfLog: "shell"
        )
        captureStep("launch", app: app)

        let shell = AppPage(app: app)
        try step("tabs-visible", app: app) {
            shell.assertAllTabsVisible()
        }

        // ── 1. Bookshelf: a real seeded book card must render ────────────────
        let bookshelf = shell.goToBookshelf()
        guard bookshelf.anyBookCard.waitUntilExists(timeout: 10) else {
            captureStep("no-book-card", app: app)
            XCTFail("bookshelf fixture (with_books_library) should render at least one real book card")
            return
        }
        try step("bookshelf-content", app: app) {
            XCTAssertTrue(shell.bookshelfTab.isSelected, "書庫 tab did not become selected")
            shell.assertNavigationChrome(on: "bookshelf")
        }

        // ── 2. Podcast: the seeded series card must render ───────────────────
        let podcast = shell.goToPodcasts()
        guard podcast.anySeriesCard.waitUntilExists(timeout: 10) else {
            captureStep("no-series-card", app: app)
            XCTFail("podcast playablePreview fixture should render a series card on the podcast tab")
            return
        }
        try step("podcast-content", app: app) {
            XCTAssertTrue(shell.podcastTab.isSelected, "播客 tab did not become selected")
            shell.assertNavigationChrome(on: "podcast")
        }

        // ── 3. Notebook: the seeded shell notebook card must render ──────────
        let notebook = shell.goToNotebooks()
        guard notebook.notebookCard(id: shellNotebookId).waitUntilExists(timeout: 10) else {
            captureStep("no-notebook-card", app: app)
            XCTFail("shell navigation fixture should render notebook card \(shellNotebookId)")
            return
        }
        try step("notebook-content", app: app) {
            XCTAssertTrue(shell.notebookTab.isSelected, "單字本 tab did not become selected")
            shell.assertNavigationChrome(on: "notebook")
        }

        // ── 4. Overview: stats content must render from the seeded synced
        //      vocab + review records (not the loading / empty / logged-out state).
        let overview = shell.goToOverview()
        guard overview.statsContent.waitUntilExists(timeout: 10) else {
            captureStep("no-overview-stats", app: app)
            XCTFail("overview tab should render real stats content from seeded synced entries + review records")
            return
        }
        try step("overview-content", app: app) {
            XCTAssertTrue(shell.overviewTab.isSelected, "總覽 tab did not become selected")
            shell.assertNavigationChrome(on: "overview")
        }

        // ── 5. Cross-tab state preservation: push podcast series detail,
        //      leave the tab, come back — the navigation stack must survive.
        shell.goToPodcasts()
        try step("podcast-series-pushed", app: app) {
            podcast.tapFirstSeries()
            XCTAssertTrue(app.waitForNavigationToSettle())
        }
        guard podcast.anyEpisodeRow.waitUntilExists(timeout: 10) else {
            captureStep("no-episode-row", app: app)
            XCTFail("podcast series detail should list at least one episode row")
            return
        }
        captureStep("podcast-episode-list", app: app)

        try step("bookshelf-reentry", app: app) {
            shell.goToBookshelf()
            XCTAssertTrue(
                bookshelf.anyBookCard.waitUntilExists(timeout: 5),
                "re-entering bookshelf must still render the seeded book card"
            )
        }

        shell.goToPodcasts()
        guard podcast.anyEpisodeRow.waitUntilExists(timeout: 5) else {
            captureStep("podcast-stack-reset", app: app)
            XCTFail("returning to the podcast tab must preserve the pushed series detail (navigation stack reset)")
            return
        }
        try step("podcast-stack-preserved", app: app) {
            XCTAssertTrue(shell.podcastTab.isSelected, "播客 tab did not become selected on re-entry")
            shell.assertNavigationChrome(on: "podcast-reentry")
        }
    }
}
