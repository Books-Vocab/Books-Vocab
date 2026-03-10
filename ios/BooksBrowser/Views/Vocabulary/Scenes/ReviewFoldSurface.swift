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
    @Environment(\.vocabSkin) private var vocabSkin

    let position: FoldSegmentPosition
    @ViewBuilder let content: () -> Content

    var body: some View {
        content()
            .background(vocabSkin.palette.cardBackground.opacity(0.985))
            .clipShape(shape)
            .overlay(shape.stroke(vocabSkin.palette.cardBorder.opacity(TodayReviewMetrics.cardBorderActiveOpacity), lineWidth: 1))
            .overlay(alignment: .top) {
                if position != .top && position != .single {
                    Rectangle()
                        .fill(vocabSkin.palette.divider.opacity(TodayReviewMetrics.dividerFillOpacity))
                        .frame(height: 0.5)
                        .padding(.horizontal, vocabSkin.spacing.cardPadding)
                }
            }
            .shadow(
                color: vocabSkin.palette.shadow.opacity(position == .single ? 1 : AppShadows.panelOpacity),
                radius: 6,
                y: AppShadows.coverY
            )
    }

    private var shape: UnevenRoundedRectangle {
        let topR = (position == .single || position == .top) ? vocabSkin.radii.card : TodayReviewMetrics.foldJoinRadius
        let botR = (position == .single || position == .bottom) ? vocabSkin.radii.card : TodayReviewMetrics.foldJoinRadius
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
    @Environment(\.vocabSkin) private var vocabSkin
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: "chevron.up")
                .font(vocabSkin.typography.iconTiny.weight(.bold))
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .frame(width: vocabSkin.metrics.reviewChevronButtonSize, height: vocabSkin.metrics.reviewChevronButtonSize)
                .background(Circle().fill(vocabSkin.palette.mutedFill.opacity(0.96)))
                .overlay(Circle().stroke(vocabSkin.palette.cardBorder.opacity(TodayReviewMetrics.cardBorderActiveOpacity), lineWidth: 1))
        }
        .buttonStyle(.plain)
        .contentShape(Circle())
    }
}

// MARK: - Fold Chevron Pill (centered collapse handle)

struct ReviewFoldChevronPill: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: "chevron.up")
                .font(vocabSkin.typography.iconTiny.weight(.bold))
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .frame(width: 48, height: vocabSkin.metrics.reviewChevronButtonSize)
                .background(Capsule(style: .continuous).fill(vocabSkin.palette.mutedFill.opacity(0.96)))
                .overlay(Capsule(style: .continuous).stroke(vocabSkin.palette.cardBorder.opacity(TodayReviewMetrics.cardBorderActiveOpacity), lineWidth: 1))
        }
        .buttonStyle(.plain)
        .contentShape(Capsule())
    }
}

// MARK: - Paper Fold Transition

private struct PaperFoldModifier: ViewModifier {
    let progress: CGFloat

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

extension AnyTransition {
    static var paperFoldFromTop: AnyTransition {
        .modifier(
            active: PaperFoldModifier(progress: 0),
            identity: PaperFoldModifier(progress: 1)
        )
    }
}
