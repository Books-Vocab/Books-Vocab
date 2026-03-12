import SwiftUI

// MARK: - Swipe Deck (card stack + swipe gesture)

extension TodayReviewPresenter {

    func cardStackLayers() -> some View {
        ZStack(alignment: .top) {
            if state.remainingCount >= 2 { stackCard(depth: 2) }
            if state.remainingCount >= 1 { stackCard(depth: 1) }
        }
    }

    func stackCard(depth: Int) -> some View {
        let progress = dismissProgress
        let effectiveDepth = CGFloat(depth) * (1.0 - progress)
        let scale: CGFloat = 1.0 - effectiveDepth * 0.025
        let yOff: CGFloat = effectiveDepth * 5
        let rotation = stackRotations[depth - 1] * Double(1.0 - progress)
        let baseOpacity = depth == 1 ? TodayReviewMetrics.cardBorderActiveOpacity : 0.35
        let targetOpacity: Double = depth == 1 ? 1.0 : TodayReviewMetrics.cardBorderActiveOpacity
        let opacity = baseOpacity + (targetOpacity - baseOpacity) * Double(progress)

        return ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                .fill(vocabSkin.palette.cardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                        .stroke(vocabSkin.palette.cardBorder.opacity(TodayReviewMetrics.cardBorderOpacity), lineWidth: 1)
                )
                .shadow(color: vocabSkin.palette.shadow.opacity(0.18), radius: 2, y: 1)

            if depth == 1, let nextCard = state.nextCard {
                reviewCardFront(nextCard.card)
                    .allowsHitTesting(false)
            }
        }
        .frame(height: frontCardHeight)
        .scaleEffect(scale)
        .offset(y: yOff)
        .rotationEffect(.degrees(rotation), anchor: .center)
        .opacity(opacity)
    }

    // MARK: Swipe Gesture + Fling Animation

    var screenWidth: CGFloat { containerWidth }

    var cardOpacity: Double {
        1.0 - Double(abs(swipeOffset)) / screenWidth * (1.0 - vocabSkin.metrics.reviewSwipeOpacityFloor)
    }

    /// 甩出進度 (0=靜止, 1=完全離開) — 驅動牌堆同步升頂
    var dismissProgress: CGFloat {
        let promotionDistance = vocabSkin.metrics.reviewSwipeThreshold * 1.15
        return min(abs(swipeOffset) / max(promotionDistance, 1), 1.0)
    }

    var swipeEnabled: Bool {
        dismissPhase == .idle && !state.isAutoPlaying
    }

    var swipeDragGesture: some Gesture {
        DragGesture(minimumDistance: 15, coordinateSpace: .local)
            .onChanged { value in
                guard swipeEnabled else { return }
                guard abs(value.translation.width) > abs(value.translation.height) else { return }
                swipeOffset = value.translation.width
            }
            .onEnded { value in
                guard swipeEnabled else { return }
                let threshold = vocabSkin.metrics.reviewSwipeThreshold
                if value.translation.width < -threshold {
                    flingCard(direction: -1, callback: onForgot)
                } else if value.translation.width > threshold {
                    flingCard(direction: 1, callback: onRemembered)
                } else {
                    withAnimation(AppMotion.reviewSubmitSnapBack) {
                        swipeOffset = 0
                    }
                }
            }
    }

    /// 統一的甩出動畫 — swipe 和按鈕共用
    func flingCard(direction: CGFloat, callback: @escaping () -> Void) {
        guard dismissPhase == .idle else { return }
        dismissPhase = .animatingOut
        lastDismissDirection = direction
        flingHapticTrigger += 1

        withAnimation(AppMotion.reviewSubmitFling) {
            swipeOffset = direction * screenWidth * 1.3
        }

        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(TodayReviewMetrics.submitCommitDelayMs))

            var noAnim = Transaction(animation: nil)
            noAnim.disablesAnimations = true
            withTransaction(noAnim) {
                suppressTransition = true
                swipeOffset = 0
                stackRotations = [.random(in: -1...1), .random(in: -1...1)]
            }
            suppressTransition = false
            withAnimation(AppMotion.reviewSubmitSettle) {
                callback()
            }

            dismissPhase = .idle
        }
    }
}
