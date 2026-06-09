#if os(iOS)
import SwiftUI

struct ReaderStepControlButton: View {
    @ObserveInjection private var inject
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
        .enableInjection()
    }
}

#Preview("ReaderStepControlButton") {
    AppThemeContainer {
        ReaderStepControlButtonPreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

struct ReaderStepControlButtonPreview: View {
    @Environment(\.appSkin) private var appSkin

    var body: some View {
        HStack(spacing: AppSpacing.s3) {
            ReaderStepControlButton(label: "A−", font: appSkin.typography.body, enabled: true) {}
            ReaderStepControlButton(label: "A＋", font: appSkin.typography.body, enabled: false) {}
        }
        .padding()
        .background(appSkin.palette.pageBackground.ignoresSafeArea())
    }
}
#endif
