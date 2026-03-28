import SwiftUI

struct AppToast: View {
    @Environment(\.appTheme) private var appTheme
    let item: AppToastItem
    let onDismiss: () -> Void

    @State private var dragOffset: CGFloat = 0

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: item.systemImage)
                .font(AppFonts.caption())
                .foregroundStyle(tintColor)

            Text(item.message.localized)
                .font(AppFonts.caption(weight: .semibold))
                .foregroundStyle(tintColor)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .background(
            Capsule()
                .fill(tintColor.opacity(0.12))
                .overlay(
                    Capsule()
                        .strokeBorder(tintColor.opacity(0.18), lineWidth: AppMetrics.dividerStandard)
                )
        )
        .background(
            Capsule()
                .fill(appTheme.palette.cardBackground)
        )
        .shadow(
            color: .black.opacity(AppShadows.toastOpacity),
            radius: AppShadows.toastRadius,
            y: AppShadows.toastY
        )
        .offset(y: min(dragOffset, 0))
        .gesture(
            DragGesture()
                .onChanged { value in
                    dragOffset = value.translation.height
                }
                .onEnded { value in
                    if value.translation.height < -20
                        || value.predictedEndTranslation.height < -200
                    {
                        onDismiss()
                    } else {
                        withAnimation(AppMotion.swipeSnapBackSpring) {
                            dragOffset = 0
                        }
                    }
                }
        )
        .accessibilityElement(children: .combine)
        .padding(.top, AppMetrics.spacingSmall)
    }

    private var tintColor: Color {
        switch item.style {
        case .success: appTheme.palette.success
        case .info: appTheme.palette.accent
        case .warning: appTheme.palette.warning
        case .error: appTheme.palette.destructive
        }
    }
}

#Preview("Toast Styles") {
    AppThemeContainer {
        AppToastPreviewScene()
    }
}

private struct AppToastPreviewScene: View {
    @Environment(\.appTheme) private var appTheme

    var body: some View {
        VStack(spacing: 24) {
            AppToast(
                item: .init(message: "已複製", style: .success),
                onDismiss: {}
            )
            AppToast(
                item: .init(message: "背景同步完成，新增 3 個單字", style: .info),
                onDismiss: {}
            )
            AppToast(
                item: .init(message: "部分同步失敗，2 個單字未上傳", style: .warning),
                onDismiss: {}
            )
            AppToast(
                item: .init(message: "刪除失敗", style: .error),
                onDismiss: {}
            )
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(appTheme.palette.pageBackground)
    }
}
