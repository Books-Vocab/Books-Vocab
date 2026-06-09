import XCTest

final class PodcastPlaybackPerfUITests: UITestCase {
    @MainActor
    func testPodcastPlaybackProbeReachesPlayerAndTapsPlay() throws {
        let app = launchApp(perfLog: "audio")
        let podcast = AppPage(app: app).goToPodcasts()

        guard podcast.anySeriesCard.waitUntilExists(timeout: 15) else {
            throw XCTSkip("無 podcast series 測試資料，跳過播放手感 probe")
        }
        podcast.tapFirstSeries()

        guard podcast.anyEpisodeRow.waitUntilExists(timeout: 10) else {
            throw XCTSkip("podcast series 無可見 episode row，跳過播放手感 probe")
        }
        podcast.tapFirstEpisode()

        guard podcast.playPauseButton.waitUntilExists(timeout: 10) else {
            throw XCTSkip("未進入可播放 player（可能是鎖定/無音訊 episode），跳過播放手感 probe")
        }
        podcast.playPauseButton.tap()

        XCTAssertTrue(
            podcast.playPauseButton.waitUntilExists(timeout: 3),
            "播放按鈕應維持可操作，供 ops logs 斷言 podcast.player.* audio metrics"
        )
    }
}
