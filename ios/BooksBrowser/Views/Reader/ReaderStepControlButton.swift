import SwiftUI

struct ReaderStepControlButton: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let label: String
    let font: Font
    let enabled: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VocabChromeSurface(
                fill: vocabSkin.palette.pageBackground,
                border: vocabSkin.palette.cardBorder
            ) {
                Text(label)
                    .font(font)
                    .foregroundStyle(enabled ? vocabSkin.palette.primaryText : vocabSkin.palette.quaternaryText)
                    .frame(width: AppMetrics.iconButtonSize, height: AppMetrics.iconButtonSize)
            }
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}
