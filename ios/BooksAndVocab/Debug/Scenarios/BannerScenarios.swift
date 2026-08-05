#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for lightweight banner components:
/// - `AppBanner` (shared inline status strip — success / warning, with actions)
/// - `VocabReviewBanner` (Vocabulary review CTA, with due/unlearned/mixed states)
/// - `DemoBanner` (Welcome demo-mode strip)
///
/// All are pure-SwiftUI views with synchronous inits, so scenarios can
/// construct them directly inside the Scenario closures. They are wrapped in
/// a padded scene to give the snapshot meaningful surrounding context.
enum BannerScenarios {
    static func register(in playbook: Playbook) {
        // MARK: App Banner
        //
        // Rendered next to a card so the snapshot answers the question the
        // redesign was about: does the banner belong beside the surfaces it
        // ships against, or does it read as chrome dropped into content?
        playbook.addScenarios(of: "Banners · App") {
            Scenario("Success (vocabulary updated)", layout: .fillH) {
                AppBannerScene(
                    message: L10n.string("單字庫已更新"),
                    systemImage: "checkmark.circle.fill",
                    tone: .success,
                    hasRetry: false
                )
            }
            Scenario("Success (already up to date)", layout: .fillH) {
                AppBannerScene(
                    message: L10n.string("單字庫已是最新"),
                    systemImage: "checkmark.circle.fill",
                    tone: .success,
                    hasRetry: false
                )
            }
            Scenario("Warning · offline, retryable", layout: .fillH) {
                AppBannerScene(
                    message: KGError.offline.localizedDescription,
                    systemImage: "wifi.slash",
                    tone: .warning,
                    hasRetry: true
                )
            }
            Scenario("Warning · long message wraps", layout: .fillH) {
                AppBannerScene(
                    message: KGError.httpError(
                        statusCode: 503,
                        detail: "upstream temporarily unavailable, please retry shortly"
                    ).localizedDescription,
                    systemImage: "exclamationmark.triangle.fill",
                    tone: .warning,
                    hasRetry: true
                )
            }
        }

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

/// `AppBanner` in situ: page background, a neighbouring card, real page insets.
/// A banner rendered on a bare white sheet always looks fine — the failure mode
/// being guarded here is only visible next to the surfaces it actually ships
/// beside.
private struct AppBannerScene: View {
    let message: String
    let systemImage: String
    let tone: AppBanner.Tone
    let hasRetry: Bool

    var body: some View {
        AppThemeContainer {
            AppBannerSceneContent(
                message: message,
                systemImage: systemImage,
                tone: tone,
                hasRetry: hasRetry
            )
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

private struct AppBannerSceneContent: View {
    @Environment(\.appTheme) private var appTheme
    let message: String
    let systemImage: String
    let tone: AppBanner.Tone
    let hasRetry: Bool

    var body: some View {
        VStack(spacing: AppSpacing.s3) {
            AppBanner(
                message: message,
                systemImage: systemImage,
                tone: tone,
                onRetry: hasRetry ? {} : nil,
                onDismiss: {}
            )

            AppSectionCard {
                VStack(alignment: .leading, spacing: AppSpacing.s2) {
                    Text(verbatim: "lascivious")
                        .font(AppFonts.body(weight: .semibold))
                        .foregroundStyle(appTheme.palette.primaryText)
                    Text(verbatim: "hors d’oeuvres")
                        .font(AppFonts.body(weight: .semibold))
                        .foregroundStyle(appTheme.palette.primaryText)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            Spacer()
        }
        .padding(AppSpacing.s4)
        .background(appTheme.palette.pageBackground.ignoresSafeArea())
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
