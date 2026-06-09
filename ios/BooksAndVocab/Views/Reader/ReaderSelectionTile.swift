#if os(iOS)
import SwiftUI

struct ReaderSelectionTile<Content: View>: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let isSelected: Bool
    @ViewBuilder let content: Content

    var body: some View {
        VocabChromeSurface(
            fill: isSelected ? appSkin.palette.mutedFill : appSkin.palette.pageBackground,
            border: isSelected
                ? appSkin.palette.cardBorder
                : appSkin.palette.divider.opacity(ReaderMetrics.settingsDividerOpacity)
        ) {
            content
                .foregroundStyle(isSelected ? appSkin.palette.primaryText : appSkin.palette.secondaryText)
        }
        .accessibilityAddTraits(isSelected ? .isSelected : [])
        .enableInjection()
    }
}

#Preview("ReaderSelectionTile") {
    AppThemeContainer {
        ReaderSelectionTilePreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

struct ReaderSelectionTilePreview: View {
    @Environment(\.appSkin) private var appSkin

    var body: some View {
        HStack(spacing: AppSpacing.s3) {
            ReaderSelectionTile(isSelected: true) {
                Text("已選").padding(AppSpacing.s3)
            }
            ReaderSelectionTile(isSelected: false) {
                Text("未選").padding(AppSpacing.s3)
            }
        }
        .padding()
        .background(appSkin.palette.pageBackground.ignoresSafeArea())
    }
}
#endif
