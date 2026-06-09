#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for lightweight banner components:
/// - `VocabReviewBanner` (Vocabulary review CTA, with due/unlearned/mixed states)
/// - `DemoBanner` (Welcome demo-mode strip)
///
/// Both are pure-SwiftUI views with synchronous inits, so scenarios can
/// construct them directly inside the Scenario closures. They are wrapped in
/// a padded scene to give the snapshot meaningful surrounding context.
enum BannerScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Review Banner
        playbook.addScenarios(of: "Banners · Review") {
            Scenario("Both types (mixed)", layout: .fillH) {
                ReviewBannerScene(dueCount: 42, unlearnedCount: 12)
            }
            Scenario("Due only", layout: .fillH) {
                ReviewBannerScene(dueCount: 5, unlearnedCount: 0)
            }
            Scenario("Unlearned only", layout: .fillH) {
                ReviewBannerScene(dueCount: 0, unlearnedCount: 3)
            }
            Scenario("Large counts (stress)", layout: .fillH) {
                ReviewBannerScene(dueCount: 1280, unlearnedCount: 999)
            }
        }

        // MARK: Demo Banner
        playbook.addScenarios(of: "Banners · Demo") {
            Scenario("Default", layout: .fill) {
                DemoBannerScene()
            }
        }
    }
}

// MARK: - Scene harnesses

private struct ReviewBannerScene: View {
    let dueCount: Int
    let unlearnedCount: Int

    var body: some View {
        AppThemeContainer {
            VStack {
                VocabReviewBanner(
                    dueCount: dueCount,
                    unlearnedCount: unlearnedCount,
                    onStartDue: {},
                    onStartUnlearned: {},
                    onStartMixed: {}
                )
                Spacer()
            }
            .padding(AppSpacing.s4)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

private struct DemoBannerScene: View {
    var body: some View {
        AppThemeContainer {
            DemoBannerContent()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

private struct DemoBannerContent: View {
    @Environment(\.appTheme) private var appTheme

    var body: some View {
        VStack(spacing: 0) {
            DemoBanner(onExit: {})
            Spacer()
        }
        .background(appTheme.palette.pageBackground.ignoresSafeArea())
    }
}
#endif
