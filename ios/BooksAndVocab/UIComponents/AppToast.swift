import SwiftUI

/// 頂端滑出的通知 pill（#2047）：只負責通知，沒有動作按鈕；單行，過長時先縮小再
/// 尾端截斷，不換行。何時用 pill、何時用畫面內面板見 docs/sop/ui-design.md「暫時性提示」。
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
                .accessibilityHidden(true)

            Text(item.message.localized)
                .font(AppFonts.caption(weight: .semibold))
                .foregroundStyle(tintColor)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
                .truncationMode(.tail)
                // 同一事件就地取代時只換字，不重播整個進出場。
                .contentTransition(.opacity)
        }
        .padding(.horizontal, AppSpacing.cardPadding)
        .padding(.vertical, AppSkin.baseSpacing.compactRowVerticalPadding)
        // Toast is a single transient glass surface. The tint carries the
        // semantic tone; Liquid Glass owns the backdrop, edge highlight and
        // depth, so no second background, border or app elevation is layered on.
        .glassEffect(
            .regular.tint(tintColor.opacity(0.12)),
            in: AppRoundedRect(roundness: AppRoundness.pill)
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
        .accessibilityIdentifier("app.toast")
        .accessibilityValue(item.style.accessibilityValue)
        // 長文案在 pill 內截斷，而不是讓 pill 貼齊螢幕邊緣。
        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
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

private extension AppToastItem.Style {
    /// UITest 可讀的語氣標記（非使用者文案）。
    var accessibilityValue: String {
        switch self {
        case .success: "success"
        case .info: "info"
        case .warning: "warning"
        case .error: "error"
        }
    }
}

// MARK: - Toast Overlay Modifier

private struct ToastOverlayModifier: ViewModifier {
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content.overlay(alignment: .top) {
            if let toast = toastCoordinator.current {
                AppToast(item: toast, onDismiss: { toastCoordinator.dismiss() })
                    // 進出場都由 coordinator 以 `AppMotion.panelState` 驅動；Reduce Motion
                    // 時只淡入淡出、不位移。
                    .transition(reduceMotion ? .overlayFade : .bannerReveal)
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
