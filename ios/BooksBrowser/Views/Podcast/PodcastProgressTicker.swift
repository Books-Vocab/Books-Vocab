#if os(iOS)
import SwiftUI

/// 把 15Hz `currentTime` 的 `@Observable` 訂閱關進一個只渲染 `Color.clear` 的葉子
/// view,使父層 `PodcastPlayerView.body` 不再訂閱 currentTime。
///
/// 背景:`@Observable` 的失效粒度是 per-view-body——某個 view 的 body 在求值時讀了
/// 哪些 property,就只訂閱那些。先前進度持久化的 `.onChange(of: vm.currentTime)` 直接
/// 掛在 `playerCore`,等於讓整個 player body 訂閱 15Hz 的 currentTime,每 tick 連鎖
/// 重建非 Equatable 的字幕子樹 + 每秒重建 follow `TimelineView` 15 次 → 捲動卡頓 +
/// 自動捲動失效。把讀取隔離到這個無子樹的葉子後,每 tick 只重求值一個 `Color.clear`
/// (O(1)),父 body 與字幕子樹不再被 currentTime 牽連。
///
/// `onTick` 僅在 `state == .playing` 時呼叫,保留原 `.onChange` 的語意(節流/持久化
/// gating 仍由呼叫端 `saveProgressIfNeeded` 的 `lastSavedTime` 判斷負責)。
struct PodcastProgressTicker: View {
    let viewModel: PodcastPlayerViewModel
    let onTick: (TimeInterval) -> Void

    var body: some View {
        Color.clear
            .onChange(of: viewModel.currentTime) { _, newTime in
                guard viewModel.state == .playing else { return }
                onTick(newTime)
            }
    }
}
#endif
