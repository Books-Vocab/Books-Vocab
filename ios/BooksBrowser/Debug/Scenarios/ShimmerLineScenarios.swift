#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the `ShimmerLine` loading placeholder.
/// `ShimmerLine` takes no init parameters: it renders a fixed 140×10 rounded
/// bar (`maxWidth: .infinity` leading) that breathes between two opacities via
/// `onAppear`. Scenarios render a single bar plus a stacked multi-line skeleton
/// to mimic a loading detail block.
enum ShimmerLineScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Word Detail · Shimmer") {
            Scenario("Shimmer Line", layout: .compressed) {
                AppThemeContainer {
                    ShimmerLine()
                        .padding()
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Shimmer Skeleton Stack", layout: .compressed) {
                AppThemeContainer {
                    VStack(alignment: .leading, spacing: AppSpacing.s3) {
                        ShimmerLine()
                        ShimmerLine()
                        ShimmerLine()
                    }
                    .frame(width: 280)
                    .padding()
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }
}
#endif
