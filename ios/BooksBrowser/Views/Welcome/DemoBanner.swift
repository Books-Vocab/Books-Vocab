import SwiftUI

struct DemoBanner: View {
    @Environment(\.appTheme) private var appTheme
    let onExit: () -> Void

    var body: some View {
        HStack(spacing: AppMetrics.spacingSmall) {
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
        .padding(.vertical, AppMetrics.spacingSmall)
        .background(appTheme.palette.accent.opacity(0.08))
    }
}
