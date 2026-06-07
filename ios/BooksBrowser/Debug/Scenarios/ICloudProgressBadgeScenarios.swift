#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `ICloudProgressBadge` (書架卡片上的 iCloud 下載進度徽章).
///
/// 純值元件 — 只吃 `progress: Double`,init 同步且非 @MainActor,因此可直接在
/// Scenario 閉包內構造。徽章為固定 32×32 圓形,前景 `.white`、背景
/// `.ultraThinMaterial`,所以包在帶顏色的 padded 容器中讓 material / 白色描邊
/// 與數字讀得出來。每個狀態對應一個下載百分比(0 / 部分 / 完成)。
enum ICloudProgressBadgeScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "iCloud Progress Badge") {
            Scenario("剛開始 (0%)", layout: .compressed) {
                ICloudProgressBadgeScene(progress: 0)
            }
            Scenario("下載中 (25%)", layout: .compressed) {
                ICloudProgressBadgeScene(progress: 0.25)
            }
            Scenario("下載中 (50%)", layout: .compressed) {
                ICloudProgressBadgeScene(progress: 0.5)
            }
            Scenario("下載中 (75%)", layout: .compressed) {
                ICloudProgressBadgeScene(progress: 0.75)
            }
            Scenario("完成 (100%)", layout: .compressed) {
                ICloudProgressBadgeScene(progress: 1)
            }
        }
    }
}

// MARK: - Scene harness

private struct ICloudProgressBadgeScene: View {
    let progress: Double

    var body: some View {
        AppThemeContainer {
            ICloudProgressBadge(progress: progress)
                .padding(AppSpacing.s6)
                .background(AppColors.accentLight)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
