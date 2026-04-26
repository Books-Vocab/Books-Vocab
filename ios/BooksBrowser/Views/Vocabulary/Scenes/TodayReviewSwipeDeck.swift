import SwiftUI

// MARK: - Swipe Deck (card stack + swipe gesture)

extension TodayReviewPresenter {

    func cardStackLayers() -> some View {
        ZStack(alignment: .top) {
            if state.remainingCount >= 2 { stackCard(depth: 2) }
            if state.remainingCount >= 1 { stackCard(depth: 1) }
        }
        .drawingGroup(opaque: false)
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
        min(abs(swipeOffset) / 200, 1.0)
    }

    var swipeEnabled: Bool {
        dismissPhase == .idle && !state.isAutoPlaying
    }

    var swipeDragGesture: some Gesture {
        DragGesture(minimumDistance: 15, coordinateSpace: .local)
            .onChanged { value in
                guard swipeEnabled else { return }
                guard abs(value.translation.width) > abs(value.translation.height) else { return }
                withAnimation(AppMotion.swipeTrackingSpring) {
                    swipeOffset = value.translation.width
                }
            }
            .onEnded { value in
                guard swipeEnabled else { return }
                let threshold = vocabSkin.metrics.reviewSwipeThreshold
                if value.translation.width < -threshold {
                    flingCard(direction: -1, velocity: abs(value.velocity.width), callback: onForgot)
                } else if value.translation.width > threshold {
                    flingCard(direction: 1, velocity: abs(value.velocity.width), callback: onRemembered)
                } else {
                    withAnimation(AppMotion.swipeSnapBackSpring) {
                        swipeOffset = 0
                    }
                }
            }
    }

    /// 統一的甩出動畫 — swipe 和按鈕共用
    func flingCard(direction: CGFloat, velocity: CGFloat = 1200, callback: @escaping () -> Void) {
        guard dismissPhase == .idle else { return }
        dismissPhase = .animatingOut
        frozenSwipeIntensity = swipeIntensity
        flingHapticTrigger += 1

        let distance = screenWidth * 1.3 + min(velocity / 2000, 0.5) * screenWidth * 0.4

        // Completion block — shared between animation callback and safety fallback
        let completeFling: @MainActor @Sendable () -> Void = { [self] in
            guard dismissPhase == .animatingOut else { return }
            var noAnim = Transaction(animation: nil)
            noAnim.disablesAnimations = true
            withTransaction(noAnim) {
                suppressTransition = true
                frozenSwipeIntensity = 0
                swipeOffset = 0
                stackRotations = [.random(in: -1...1), .random(in: -1...1)]
                callback()
                dismissPhase = .idle
            }
            DispatchQueue.main.async {
                suppressTransition = false
            }
        }

        withAnimation(AppMotion.swipeFlingSpring, completionCriteria: .logicallyComplete) {
            swipeOffset = direction * distance
        } completion: {
            completeFling()
        }

        // Safety fallback: if animation completion never fires (macOS edge case),
        // force-complete after a generous timeout to prevent UI deadlock.
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(0.8 * 1_000_000_000))
            completeFling()
        }
    }
}
