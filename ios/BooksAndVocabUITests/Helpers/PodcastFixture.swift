import Foundation

/// 跨 UITest 共用的 podcast fixture 常數。
/// 素材路徑、集數與 gating 狀態由 UI World (`runtimePodcast`) 管；此檔只保留
/// 測試需要的 server 隔離與 accessibility id。
enum PodcastFixture {
    /// auth tieredCatalog flow（auth / pro）用：不可達 server。
    /// 假 token 打真 backend 的 401 會觸發 logout + clearLocalData 清掉 fixture 世界；
    /// 指向 connection-refused 位址（非 401）→ 不登出。
    static let tieredCatalogEnvironment: [String: String] = [
        "KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"
    ]

    /// auth tieredCatalog fixture（`UITestFixtureSeed+Auth`）種出的 id，與 seed 對齊。
    /// `seriesID` 是裸 id（配 `PodcastPage.seriesCard(id:)`，它自拼 `podcast.series.` 前綴）；
    /// episode id 是完整 AX identifier（配 `PodcastPage.episodeRow(_:)`）。
    static let seriesID = "ui-auth-series"
    static let episode1RowID = "podcast.episode.ui-auth-series_ep_01"
    static let episode2RowID = "podcast.episode.ui-auth-series_ep_02"
}
