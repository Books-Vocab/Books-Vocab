#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `PodcastBadge` — a stateless waveform chip whose
/// appearance is driven entirely by the ambient `appSkin`. Variants exercise
/// the badge standalone, on different backgrounds, and overlaid on a thumbnail.
enum PodcastBadgeScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Podcast Badge") {
            Scenario("Default", layout: .fill) {
                AppThemeContainer {
                    PodcastBadge()
                        .padding()
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("On Card Surface", layout: .fill) {
                AppThemeContainer {
                    PodcastBadgeOnSurfaceScene()
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Overlay On Thumbnail", layout: .fill) {
                AppThemeContainer {
                    PodcastBadgeOverlayScene()
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }
}

// MARK: - Scene harnesses

private struct PodcastBadgeOnSurfaceScene: View {
    @Environment(\.appSkin) private var skin

    var body: some View {
        ZStack {
            skin.palette.pageBackground.ignoresSafeArea()
            RoundedRectangle(cornerRadius: 16)
                .fill(skin.palette.cardBackground)
                .frame(width: 200, height: 120)
                .overlay(alignment: .topTrailing) {
                    PodcastBadge()
                }
        }
    }
}

private struct PodcastBadgeOverlayScene: View {
    @Environment(\.appSkin) private var skin

    var body: some View {
        ZStack {
            skin.palette.pageBackground.ignoresSafeArea()
            RoundedRectangle(cornerRadius: 12)
                .fill(
                    LinearGradient(
                        colors: [skin.palette.accent, skin.palette.mutedFill],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .frame(width: 140, height: 140)
                .overlay(alignment: .bottomLeading) {
                    PodcastBadge()
                }
        }
    }
}
#endif
