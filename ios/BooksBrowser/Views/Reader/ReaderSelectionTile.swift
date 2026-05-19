#if os(iOS)
import SwiftUI

struct ReaderSelectionTile<Content: View>: View {
    @Environment(\.appSkin) private var appSkin
    let isSelected: Bool
    @ViewBuilder let content: Content

    var body: some View {
        VocabChromeSurface(
            fill: isSelected ? appSkin.palette.mutedFill : appSkin.palette.pageBackground,
            border: isSelected
                ? appSkin.palette.cardBorder
                : appSkin.palette.divider.opacity(appSkin.metrics.readerSettingsDividerOpacity)
        ) {
            content
                .foregroundStyle(isSelected ? appSkin.palette.primaryText : appSkin.palette.secondaryText)
        }
    }
}
#endif
