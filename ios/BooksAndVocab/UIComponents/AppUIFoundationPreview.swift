#if os(iOS)
import SwiftUI

/// A proof surface for the shared UI foundation used by the IOS2.0.1+7 review.
///
/// This is deliberately a preview-only composition: it does not introduce a
/// new production primitive or change any screen consumer. It keeps the
/// native-first boundary visible by showing app-drawn surfaces beside the
/// one justified Liquid Glass exception, `AppFloatingChrome`.
#Preview("UI Foundation • Native first") {
    AppThemeContainer {
        AppUIFoundationPreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

private struct AppUIFoundationPreview: View {
    @Environment(\.appTheme) private var appTheme
    @State private var selectedFilters: Set<String> = ["unlearned"]
    @State private var selectedTab = "overview"
    @Namespace private var glassNamespace

    private let options = [
        AppTabOption(id: "unlearned", title: "Unlearned", count: 12),
        AppTabOption(id: "review", title: "Review", count: 5),
        AppTabOption(id: "learned", title: "Learned", count: 27)
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AppSpacing.s5) {
                Text("Shared UI foundation")
                    .font(AppFonts.h2(weight: .semibold))
                    .foregroundStyle(appTheme.palette.primaryText)

                AppSectionCard(style: .themed(appTheme)) {
                    VStack(alignment: .leading, spacing: AppSpacing.s3) {
                        Text("App-drawn surfaces")
                            .font(AppFonts.body(weight: .semibold))
                            .foregroundStyle(appTheme.palette.primaryText)

                        AppStateMessageCard(
                            title: "Loading state",
                            systemImage: "arrow.triangle.2.circlepath",
                            description: "Shared state presentation stays separate from screen layout."
                        )
                    }
                }

                AppFilterChipBar(
                    options: options,
                    selection: $selectedFilters,
                    style: .themed(appTheme)
                )

                AppTabSelector(
                    options: options,
                    selection: $selectedTab,
                    style: .themed(appTheme)
                )

                Text("Native controls remain screen-owned; glass is limited to floating chrome.")
                    .font(AppFonts.caption())
                    .foregroundStyle(appTheme.palette.secondaryText)

                AppFloatingChrome {
                    HStack(spacing: AppSpacing.s2) {
                        AppFloatingChromeButton(
                            accessibilityLabel: "Back",
                            action: {}
                        ) {
                            Image(systemName: "chevron.left")
                        }
                        .appFloatingChromeItem(
                            union: "ui-foundation-preview",
                            in: glassNamespace
                        )

                        AppFloatingChromeButton(
                            accessibilityLabel: "More",
                            action: {}
                        ) {
                            Image(systemName: "ellipsis")
                        }
                        .appFloatingChromeItem(
                            union: "ui-foundation-preview",
                            in: glassNamespace
                        )
                    }
                }
            }
            .padding(AppSpacing.s5)
        }
        .background(appTheme.palette.pageBackground.ignoresSafeArea())
    }
}
#endif
