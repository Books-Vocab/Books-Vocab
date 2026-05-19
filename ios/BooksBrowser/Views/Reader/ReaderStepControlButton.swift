#if os(iOS)
import SwiftUI

struct ReaderStepControlButton: View {
    @Environment(\.appSkin) private var appSkin
    let label: String
    let font: Font
    let enabled: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VocabChromeSurface(
                fill: appSkin.palette.pageBackground,
                border: appSkin.palette.cardBorder
            ) {
                Text(label)
                    .font(font)
                    .foregroundStyle(enabled ? appSkin.palette.primaryText : appSkin.palette.quaternaryText)
                    .frame(width: AppMetrics.iconButtonSize, height: AppMetrics.iconButtonSize)
            }
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}
#endif
