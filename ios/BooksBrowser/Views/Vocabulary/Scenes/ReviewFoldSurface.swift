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
    @Environment(\.appSkin) private var appSkin

    let position: FoldSegmentPosition
    @ViewBuilder let content: () -> Content

    var body: some View {
        content()
            .background(appSkin.palette.cardBackground.opacity(0.985))
            .clipShape(shape)
            .overlay(shape.stroke(appSkin.palette.cardBorder.opacity(TodayReviewMetrics.cardBorderActiveOpacity), lineWidth: 1))
            .overlay(alignment: .top) {
                if position != .top && position != .single {
                    Rectangle()
                        .fill(appSkin.palette.divider.opacity(TodayReviewMetrics.dividerFillOpacity))
                        .frame(height: AppMetrics.dividerThin)
                        .padding(.horizontal, appSkin.spacing.cardPadding)
                }
            }
            .appElevation(.z1)
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

// MARK: - Fold Chevron Button

struct ReviewFoldChevronButton: View {
    @Environment(\.appSkin) private var appSkin
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: "chevron.up")
                .font(appSkin.typography.iconTiny.weight(.bold))
                .foregroundStyle(appSkin.palette.secondaryText)
                .frame(width: appSkin.metrics.reviewChevronButtonSize, height: appSkin.metrics.reviewChevronButtonSize)
                .background(Circle().fill(appSkin.palette.mutedFill.opacity(0.96)))
                .overlay(Circle().stroke(appSkin.palette.cardBorder.opacity(TodayReviewMetrics.cardBorderActiveOpacity), lineWidth: 1))
        }
        .buttonStyle(.plain)
        .contentShape(Circle())
    }
}

// MARK: - Fold Chevron Pill (centered collapse handle)

struct ReviewFoldChevronPill: View {
    @Environment(\.appSkin) private var appSkin
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: "chevron.up")
                .font(appSkin.typography.iconTiny.weight(.bold))
                .foregroundStyle(appSkin.palette.secondaryText)
                .frame(width: 48, height: appSkin.metrics.reviewChevronButtonSize)
                .background(Capsule(style: .continuous).fill(appSkin.palette.mutedFill.opacity(0.96)))
                .overlay(Capsule(style: .continuous).stroke(appSkin.palette.cardBorder.opacity(TodayReviewMetrics.cardBorderActiveOpacity), lineWidth: 1))
        }
        .buttonStyle(.plain)
        .contentShape(Capsule())
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
