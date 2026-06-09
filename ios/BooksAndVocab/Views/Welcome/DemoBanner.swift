import SwiftUI

struct DemoBanner: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    let onExit: () -> Void

    var body: some View {
        HStack(spacing: AppSpacing.s2) {
            Image(systemName: "play.circle.fill")
                .font(AppFonts.caption(weight: .medium))
            Text("Demo 模式".localized)
                .font(AppFonts.caption(weight: .medium))
            Spacer()
            Button("結束".localized, action: onExit)
                .font(AppFonts.caption(weight: .semibold))
                .foregroundStyle(appTheme.palette.accent)
        }
        .foregroundStyle(appTheme.palette.secondaryText)
        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
        .padding(.vertical, AppSpacing.s2)
        .background(appTheme.palette.accent.opacity(0.08))
        .enableInjection()
    }
}

#Preview("DemoBanner") {
    AppThemeContainer {
        DemoBannerPreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

private struct DemoBannerPreview: View {
    @Environment(\.appTheme) private var appTheme

    var body: some View {
        VStack(spacing: 0) {
            DemoBanner(onExit: {})
            Spacer()
        }
        .background(appTheme.palette.pageBackground.ignoresSafeArea())
    }
}
