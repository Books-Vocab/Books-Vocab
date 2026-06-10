import SwiftUI

// MARK: - Fold Segment Position

enum FoldSegmentPosition {
    case single
    case top
    case middle
    case bottom
}

// MARK: - Fold Surface Container

struct ReviewFoldSurface<Content: View>: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin

    let position: FoldSegmentPosition
    /// 邊框線條透明度 — 預設為 active 值；常駐 slot（Phase 3a）以
    /// `TodayReviewCardSlotLayout.borderOpacity` 內插（preview 0.45 → active 0.72）。
    var borderOpacity: Double = TodayReviewMetrics.cardBorderActiveOpacity
    @ViewBuilder let content: () -> Content

    var body: some View {
        content()
            .background(appSkin.palette.cardBackground.opacity(0.985))
            .clipShape(shape)
            .overlay(shape.stroke(appSkin.palette.cardBorder.opacity(borderOpacity), lineWidth: 1))
            .overlay(alignment: .top) {
                if position != .top && position != .single {
                    Rectangle()
                        .fill(appSkin.palette.divider.opacity(TodayReviewMetrics.dividerFillOpacity))
                        .frame(height: AppMetrics.dividerThin)
                        .padding(.horizontal, appSkin.spacing.cardPadding)
                }
            }
            .appElevation(.z1)
            .enableInjection()
    }

    private var shape: UnevenRoundedRectangle {
        let topR = (position == .single || position == .top) ? appSkin.radii.card : TodayReviewMetrics.foldJoinRadius
        let botR = (position == .single || position == .bottom) ? appSkin.radii.card : TodayReviewMetrics.foldJoinRadius
        return UnevenRoundedRectangle(
            topLeadingRadius: topR,
            bottomLeadingRadius: botR,
            bottomTrailingRadius: botR,
            topTrailingRadius: topR,
            style: .continuous
        )
    }
}

// MARK: - Fold Chevron Pill (centered collapse handle)

struct ReviewFoldChevronPill: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let action: () -> Void
    let accessibilityLabel: String

    var body: some View {
        Button(action: action) {
            Image(systemName: "chevron.up")
                .font(appSkin.typography.iconTiny.weight(.semibold))
                .foregroundStyle(appSkin.palette.tertiaryText.opacity(0.78))
                .frame(width: 34, height: 18)
                .background(
                    Capsule(style: .continuous)
                        .fill(appSkin.palette.cardBackground.opacity(0.94))
                )
                .overlay(
                    Capsule(style: .continuous)
                        .stroke(appSkin.palette.divider.opacity(0.58), lineWidth: AppSpacing.hairline)
                )
                .frame(width: 48, height: TodayReviewMetrics.chevronButtonSize)
        }
        .buttonStyle(.plain)
        .contentShape(Capsule())
        .accessibilityLabel(accessibilityLabel)
        .enableInjection()
    }
}

// MARK: - Paper Fold Modifier (Animatable)

/// 摺疊動畫 — progress 0=完全摺疊 1=完全展開。
/// 實作 Animatable 使 SwiftUI 逐幀插值 progress，
/// 確保 scaleEffect / rotation3D / opacity / offset 完美同步。
struct PaperFoldModifier: ViewModifier, Animatable {
    var progress: CGFloat

    var animatableData: CGFloat {
        get { progress }
        set { progress = newValue }
    }

    func body(content: Content) -> some View {
        content
            .scaleEffect(y: max(progress, 0.02), anchor: .top)
            .rotation3DEffect(
                .degrees(Double((1 - progress) * -88)),
                axis: (x: 1, y: 0, z: 0),
                anchor: .top,
                perspective: 0.86
            )
            .opacity(progress)
            .offset(y: (1 - progress) * -TodayReviewMetrics.paperFoldOffsetY)
    }
}
