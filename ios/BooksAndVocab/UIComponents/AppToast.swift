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
        .padding(.horizontal, AppSpacing.cardPadding)
        .padding(.vertical, AppSkin.baseSpacing.compactRowVerticalPadding)
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
        .appElevation(.z2)
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
        .padding(.top, AppSpacing.s2)
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

// MARK: - Toast Overlay Modifier

private struct ToastOverlayModifier: ViewModifier {
    @Environment(\.toastCoordinator) private var toastCoordinator

    func body(content: Content) -> some View {
        content.overlay(alignment: .top) {
            if let toast = toastCoordinator.current {
                AppToast(item: toast, onDismiss: { toastCoordinator.dismiss() })
                    .transition(.bannerReveal)
                    .zIndex(999)
            }
        }
    }
}

extension View {
    func toastOverlay() -> some View {
        modifier(ToastOverlayModifier())
    }
}

#Preview("Toast Styles") {
    AppThemeContainer {
        AppToastPreviewScene()
    }
    .environmentObject(AppAppearanceStore.preview)
}

private struct AppToastPreviewScene: View {
    @Environment(\.appTheme) private var appTheme

    var body: some View {
        VStack(spacing: AppSpacing.s6) {
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
