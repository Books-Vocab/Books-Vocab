import Foundation

/// 跨 UITest 共用的 podcast fixture 常數（auth tieredCatalog / playback probe 共吃同一支
/// lab 音檔）。原本散在 AuthFlow / ProEntitlement / PlaybackPerf 三檔逐字 copy，收斂於此。
///
/// `root` 是 podcast pipeline 的本機產物路徑（`lab/podcast/workspaces/` 在 .gitignore，
/// 音檔太大不 git-track）——repo-wide 既有慣例（ReaderFlow 等亦同），CI 由 setup 保證存在。
/// 可攜化（bundled resource / 縮編 fixture）是獨立議題，不在此檔範圍；但路徑收斂成單一來源
/// 後，pipeline 重生 workspace（hash 變動）只需改這一處。
enum PodcastFixture {
    static let root =
        "/Users/chenliangyu/project/kg/lab/podcast/workspaces/atomic_habits_an_easy_proven_w_033e3990/scripts"

    /// 三檔共用的播放素材 env（同一支 lab 音檔 / 字幕 / 時長）。
    static let assetEnvironment: [String: String] = [
        "KG_UI_TEST_PODCAST_AUDIO": "\(root)/ep_1_flash.m4a",
        "KG_UI_TEST_PODCAST_SUBTITLE": "\(root)/ep_1_flash.srt",
        "KG_UI_TEST_PODCAST_DURATION": "1034.6",
    ]

    /// auth tieredCatalog flow（auth / pro）用：素材 + 不可達 server。
    /// 假 token 打真 backend 的 401 會觸發 logout + clearLocalData 清掉 fixture 世界；
    /// 指向 connection-refused 位址（非 401）→ 不登出。
    static let tieredCatalogEnvironment: [String: String] =
        assetEnvironment.merging(["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"]) { _, new in new }

    /// auth tieredCatalog fixture（`UITestFixtureSeed+Auth`）種出的 id，與 seed 對齊。
    /// `seriesID` 是裸 id（配 `PodcastPage.seriesCard(id:)`，它自拼 `podcast.series.` 前綴）；
    /// episode id 是完整 AX identifier（配 `PodcastPage.episodeRow(_:)`）。
    static let seriesID = "ui-auth-series"
    static let episode1RowID = "podcast.episode.ui-auth-series_ep_01"
    static let episode2RowID = "podcast.episode.ui-auth-series_ep_02"
}
