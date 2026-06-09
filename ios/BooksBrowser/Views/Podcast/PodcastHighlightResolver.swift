#if os(iOS)
import Foundation

/// 解析「任一時刻唯一高亮的句子 id」。捲動領先音訊 `scrollLeadSec` 點亮即將播的句子，
/// 但高亮永遠只有一格（接力，非重疊）：
///   • `scrollLeadId` 落後或等於 `currentId`（一般播放中、或 seek 後 VM pin lead）
///     → 高亮精確的 `currentId`。
///   • `scrollLeadId` 領先 `currentId`（切換前的 scrollLeadSec 窗口）→ 高亮 `currentId + 1`。
///     clamp 到 +1 是刻意：短句可能讓 `scrollLeadId` 跳到 `currentId + 2`，那一格沒有
///     underline overlay（只有 current / next 掛載），點亮會出現 lit-but-underline-less；
///     夾到 +1（== view 的 `isNext`）保證被點亮的格子永遠有 underline machinery。
///   • `currentId` 為 nil（字幕未定位）→ 無高亮，避免初始/缺 renderState 時假亮 lead。
enum PodcastHighlightResolver {
    static func highlightId(currentId: Int?, scrollLeadId: Int?) -> Int? {
        guard let current = currentId else { return nil }
        guard let lead = scrollLeadId, lead > current else { return current }
        return current + 1
    }
}
#endif
