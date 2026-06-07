#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `PodcastProgressTicker`.
///
/// `PodcastProgressTicker` 是一個刻意「無視覺」的葉子 view：它的 body 只渲染
/// `Color.clear`,真正職責是把 15Hz 的 `viewModel.currentTime` 訂閱關進這個無子樹的
/// 葉子,並在 `state == .playing` 時透過 `onTick` 回呼。它沒有任何可視像素,因此每個
/// scenario 用一個帶邊框的容器把這個 ticker 嵌進去,讓 PNG 有可辨識的外框做視覺回歸
/// (確認它佔位 0 高/0 寬、不撐開父層),並以 label 標示狀態。
///
/// 因為 `PodcastPlayerViewModel.init(hostNames:)` 是 `@MainActor`(內部建立
/// `PodcastAudioEngine`),所以 viewModel 必須在 `@MainActor` 的 scene struct body 內
/// 建構,不能在 nonisolated 的 Scenario 閉包裡直接 new。viewModel 建構後不自動播放,
/// 故對 catalog 渲染安全(ticker 不會觸發 onTick)。
enum PodcastProgressTickerScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Podcast Progress Ticker") {
            Scenario("Idle (zero-size leaf)", layout: .compressed) {
                PodcastProgressTickerScene(label: "idle / 不可見葉子")
            }
            Scenario("With sibling content", layout: .compressed) {
                PodcastProgressTickerScene(label: "ticker 與兄弟內容並存,不撐開父層")
            }
        }
    }
}

// MARK: - Scene harness

/// `@MainActor` body so the `@MainActor` `PodcastPlayerViewModel` is constructed
/// on the main actor (the Scenario closure itself is nonisolated).
private struct PodcastProgressTickerScene: View {
    let label: String

    var body: some View {
        AppThemeContainer {
            VStack(alignment: .leading, spacing: AppSpacing.s3) {
                Text(label)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                // 被測元件:無視覺,框出它的佔位行為(應為 0×0)。
                PodcastProgressTicker(
                    viewModel: PodcastPlayerViewModel(hostNames: ["Alex", "Bea"]),
                    onTick: { _ in }
                )
                .border(Color.red.opacity(0.6))
                Text("↑ 上方為 PodcastProgressTicker(僅 Color.clear,應不佔空間)")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            .padding()
            .frame(maxWidth: 360, alignment: .leading)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
