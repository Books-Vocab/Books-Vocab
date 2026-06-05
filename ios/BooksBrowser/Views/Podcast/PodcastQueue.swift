import Foundation

/// 連續播放佇列決策（純函式）。鏡射 series 內 episode 的播放順序 + entitlement gate，
/// 與 `PodcastAccess` 一致——server 仍是安全邊界，此為自動續播時的 UX 層先攔。
enum PodcastQueue {
    /// 播完 `current` 後應自動續播的下一集；`nil` = 停止（無下一集或被 gate 擋下）。
    ///
    /// 規則：
    /// - 同 series 內 `episodeNumber` 嚴格大於 `current` 者，依序檢視。
    /// - `audioAvailable == false`（音訊尚未上架）→ 跳過，續找更後面者。
    /// - 找到第一個有音訊的後續集，依 `PodcastAccess.canPlay` 判 entitlement：
    ///   可播 → 回傳它；不可播 → 回傳 `nil`（**停在當集尾，不跨過鎖定集找更後面**）。
    ///   這確保 free 播完 ep1 preview 不會自動跳進 Pro-only ep2、guest 不自動續播。
    static func nextPlayable(
        in episodes: [PodcastEpisode],
        after current: PodcastEpisode,
        tier: PodcastTier
    ) -> PodcastEpisode? {
        let sorted = episodes.sorted { $0.episodeNumber < $1.episodeNumber }
        guard let idx = sorted.firstIndex(where: { $0.remoteId == current.remoteId }) else { return nil }
        for ep in sorted[sorted.index(after: idx)...] {
            guard ep.audioAvailable else { continue }
            return PodcastAccess.canPlay(
                tier: tier,
                episodeNumber: ep.episodeNumber,
                previewAvailable: ep.previewAvailable
            ) ? ep : nil
        }
        return nil
    }
}
