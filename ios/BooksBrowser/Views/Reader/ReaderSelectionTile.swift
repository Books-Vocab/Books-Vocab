#if os(iOS)
import SwiftUI

struct ReaderSelectionTile<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let isSelected: Bool
    @ViewBuilder let content: Content

    var body: some View {
        VocabChromeSurface(
            fill: isSelected ? vocabSkin.palette.mutedFill : vocabSkin.palette.pageBackground,
            border: isSelected
                ? vocabSkin.palette.cardBorder
                : vocabSkin.palette.divider.opacity(vocabSkin.metrics.readerSettingsDividerOpacity)
        ) {
            content
                .foregroundStyle(isSelected ? vocabSkin.palette.primaryText : vocabSkin.palette.secondaryText)
        }
    }
}
#endif
