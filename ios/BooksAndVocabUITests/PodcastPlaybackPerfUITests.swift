import XCTest

final class PodcastPlaybackPerfUITests: UITestCase {
    private let sustainedPlaybackSeconds: TimeInterval = 8
    private let minimumElapsedAdvance: TimeInterval = 4

    @MainActor
    func testPodcastPlaybackProbeSustainsRealAudioPlayback() throws {
        let podcastFixtureRoot = "/Users/chenliangyu/project/kg/lab/podcast/workspaces/atomic_habits_an_easy_proven_w_033e3990/scripts"
        let app = launchIsolatedApp(
            fixtures: [.podcastPlayablePreview],
            extraEnvironment: [
                "KG_UI_TEST_PODCAST_AUDIO": "\(podcastFixtureRoot)/ep_1_flash.m4a",
                "KG_UI_TEST_PODCAST_SUBTITLE": "\(podcastFixtureRoot)/ep_1_flash.srt",
                "KG_UI_TEST_PODCAST_DURATION": "1034.6",
                "KG_UI_TEST_PODCAST_SERIES_TITLE": "Atomic Habits",
                "KG_UI_TEST_PODCAST_EPISODE_TITLE": "Actual Lab Episode",
                "KG_UI_TEST_PODCAST_HOST": "Lab Podcast"
            ],
            perfLog: "audio"
        )
        captureStep("launch", app: app)

        let podcast = try step("podcast-tab", app: app) {
            let page = AppPage(app: app).goToPodcasts()
            XCTAssertTrue(app.waitForNavigationToSettle())
            return page
        }

        guard podcast.anySeriesCard.waitUntilExists(timeout: 15) else {
            captureStep("no-series-card", app: app)
            throw XCTSkip("無 podcast series 測試資料，跳過播放手感 probe")
        }
        try step("series-detail", app: app) {
            podcast.tapFirstSeries()
            XCTAssertTrue(app.waitForNavigationToSettle())
        }

        guard podcast.anyEpisodeRow.waitUntilExists(timeout: 10) else {
            captureStep("no-episode-row", app: app)
            throw XCTSkip("podcast series 無可見 episode row，跳過播放手感 probe")
        }
        try step("episode-tapped", app: app) {
            podcast.tapFirstEpisode()
            XCTAssertTrue(app.waitForNavigationToSettle())
        }

        if podcast.loginSheet.waitUntilExists(timeout: 1) {
            captureStep("unexpected-login-sheet", app: app)
            XCTFail("lab podcast fixture should be authenticated; login sheet means this probe is not testing playback")
            return
        }

        if podcast.playerLoginGate.waitUntilExists(timeout: 1) {
            captureStep("unexpected-player-login-gate", app: app)
            XCTFail("lab podcast fixture should satisfy podcast access; login gate means this probe is not testing playback")
            return
        }

        guard podcast.playPauseButton.waitUntilExists(timeout: 10) else {
            captureStep("player-not-playable", app: app)
            XCTFail("lab podcast fixture should reach a playable player")
            return
        }
        captureStep("player-ready", app: app)
        try step("play-tapped", app: app) {
            podcast.playPauseButton.tap()
        }

        XCTAssertTrue(
            podcast.pauseButton.waitUntilExists(timeout: 3),
            "播放後 control 必須切成 pauseButton，證明 PodcastPlayerViewModel.state == .playing"
        )
        captureStep("play-verified", app: app)

        let initialElapsed = try readElapsedSeconds(from: podcast)
        let deadline = Date().addingTimeInterval(sustainedPlaybackSeconds + 4)
        var latestElapsed = initialElapsed

        while Date() < deadline {
            if let value = Self.parseClock(podcast.elapsedTimeLabel.label) {
                latestElapsed = value
                if latestElapsed - initialElapsed >= minimumElapsedAdvance {
                    break
                }
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        }

        captureStep("playback-sustained", app: app)
        attachText(
            """
            fixtureAudio=\(podcastFixtureRoot)/ep_1_flash.m4a
            fixtureSubtitle=\(podcastFixtureRoot)/ep_1_flash.srt
            initialElapsed=\(initialElapsed)
            latestElapsed=\(latestElapsed)
            elapsedAdvance=\(latestElapsed - initialElapsed)
            requiredAdvance=\(minimumElapsedAdvance)
            observationWindow=\(sustainedPlaybackSeconds)
            """,
            named: "Podcast Sustained Playback Metrics"
        )
        XCTAssertGreaterThanOrEqual(
            latestElapsed - initialElapsed,
            minimumElapsedAdvance,
            "Podcast 必須真播放一段時間；elapsedTime 沒有足夠前進代表只切到 playing 狀態但音訊可能卡住"
        )
        XCTAssertTrue(
            podcast.pauseButton.exists,
            "長播放窗口後仍應維持 pauseButton，避免播放立即停止或重置"
        )
    }

    private func readElapsedSeconds(
        from podcast: PodcastPage,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) throws -> TimeInterval {
        XCTAssertTrue(
            podcast.elapsedTimeLabel.waitUntilExists(timeout: 3),
            "播放器必須暴露 elapsedTime 供 UITest 驗證真播放進度",
            file: file,
            line: line
        )
        guard let seconds = Self.parseClock(podcast.elapsedTimeLabel.label) else {
            XCTFail("無法解析 elapsedTime：\(podcast.elapsedTimeLabel.label)", file: file, line: line)
            throw XCTSkip("elapsedTime 不可解析")
        }
        return seconds
    }

    private static func parseClock(_ raw: String) -> TimeInterval? {
        let parts = raw.split(separator: ":").map(String.init)
        guard parts.count == 2 || parts.count == 3 else { return nil }
        let numbers = parts.compactMap(Int.init)
        guard numbers.count == parts.count else { return nil }
        if numbers.count == 2 {
            return TimeInterval(numbers[0] * 60 + numbers[1])
        }
        return TimeInterval(numbers[0] * 3600 + numbers[1] * 60 + numbers[2])
    }
}
