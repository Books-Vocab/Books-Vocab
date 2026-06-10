import SwiftUI

private let flingSafetyNetTimeout: Duration = .milliseconds(800)

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
            RoundedRectangle(cornerRadius: appSkin.radii.card, style: .continuous)
                .fill(appSkin.palette.cardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: appSkin.radii.card, style: .continuous)
                        .stroke(appSkin.palette.cardBorder.opacity(TodayReviewMetrics.cardBorderOpacity), lineWidth: 1)
                )
                .appElevation(.z1)

            if depth == 1, let nextCard = state.nextCard {
                let _ = { if progress > 0 || dismissPhase != .idle {
                    PerfLog.review.mark(
                        "stack.preview",
                        "w=\(nextCard.card.word) scale=\(String(format: "%.3f", scale)) op=\(String(format: "%.2f", opacity)) prog=\(String(format: "%.2f", progress))"
                    )
                } }()
                reviewCardFront(nextCard.card)
                    .overlay(alignment: .topTrailing) {
                        // 與作用中卡片共用 chrome 渲染（裝飾、不可點）— fling 飛出期間
                        // 背後預覽即帶完整喇叭 / 詳情圖示，完成時 swap 不再 pop。
                        frontCardChrome(nextCard.card, interactive: false)
                    }
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
        1.0 - Double(abs(swipeOffset)) / screenWidth * (1.0 - TodayReviewMetrics.swipeOpacityFloor)
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
                let threshold = TodayReviewMetrics.swipeThreshold
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
    func flingCard(direction: CGFloat, velocity: CGFloat = 1200, source: String = "swipe", callback: @escaping () -> Void) {
        guard dismissPhase == .idle else { return }
        dismissPhase = .animatingOut
        frozenSwipeIntensity = swipeIntensity
        flingHapticTrigger += 1
        let _flingStart = DispatchTime.now()
        PerfLog.review.mark("fling.start", "source=\(source) dir=\(direction) vel=\(velocity)")
        // Record the real per-frame cadence across the fly-off window. Distinguishes
        // "animation ran smoothly to completion" from "main thread idle, advance gated
        // by the 0.8s safety net" — body-eval marks can't see this (CA interpolates the
        // offset at the render layer without re-running the body each frame).
        PerfLog.review.startFrameSampler("fling.frames")
        // Second sampler over a WIDER window: fling.frames stops at fling.complete
        // (~200ms) and so cannot see the post-landing reinit storm (the detached DB
        // save → @Query invalidation → cover-closure re-run lands async, AFTER the
        // fling). settle.frames runs the full 800ms (stopped in the safety Task) to
        // capture whether that storm actually drops frames — the link the earlier
        // measurement window structurally missed.
        PerfLog.review.startFrameSampler("settle.frames")

        let distance = screenWidth * 1.3 + min(velocity / 2000, 0.5) * screenWidth * 0.4

        // Completion block — shared between animation callback and safety fallback.
        // `caller` tags WHICH path fired it: `animation` = withAnimation completion
        // fired (and anim_dur ≈ how long .logicallyComplete took for the spring);
        // `safetyNet` = the 0.8s fallback fired because completion never did. Decisive
        // discriminator for the flip→next-card pause root cause.
        let completeFling: @MainActor @Sendable (String) -> Void = { [self] caller in
            guard dismissPhase == .animatingOut else {
                PerfLog.review.mark("fling.complete.skip", "caller=\(caller) at=\(PerfChannel.ms(since: _flingStart))ms (already idle)")
                return
            }
            PerfLog.review.stopFrameSampler("fling.frames")
            var noAnim = Transaction(animation: nil)
            noAnim.disablesAnimations = true
            PerfLog.review.mark("fling.complete", "caller=\(caller) anim_dur=\(PerfChannel.ms(since: _flingStart))ms (fling.start->complete)")
            TodayReviewState.flingClock = .now()
            PerfLog.review.measure("fling.transaction") {
                withTransaction(noAnim) {
                    suppressTransition = true
                    frozenSwipeIntensity = 0
                    swipeOffset = 0
                    stackRotations = [.random(in: -1...1), .random(in: -1...1)]
                    // 幽靈背面樹（device trace 證據：settle burst 內
                    // CardDocumentExampleBlock/CardRichTextRenderer 樣本）：
                    // 從背面送出時 backContentMounted 仍 true，callback() 推進
                    // currentIndex 後 settle 幀會替「新卡」完整建出背面樹，下一幀
                    // 又被 onChange(currentCardKey) 放閘拆毀——同幀建、次幀拆的
                    // 純白工。閘必須在推進「前」放下；onChange 仍在（冪等，收
                    // previous/shuffle 等其他推進路徑）。
                    backMountGeneration += 1
                    backContentMounted = false
                    suppressFoldAnimation = true
                    callback()
                    dismissPhase = .idle
                }
            }
            DispatchQueue.main.async {
                // suppressTransition 與 suppressFoldAnimation 同一個 async 收
                // （原本分兩處 → settle 後多一次 body 重評）。
                suppressTransition = false
                suppressFoldAnimation = false
                PerfLog.review.mark("suppress.reset", "at=\(PerfChannel.ms(since: _flingStart))ms (fling.start->suppressOff)")
            }
        }

        withAnimation(AppMotion.swipeFlingSpring, completionCriteria: .logicallyComplete) {
            swipeOffset = direction * distance
        } completion: {
            completeFling("animation")
        }

        // Safety fallback: if animation completion never fires (macOS edge case),
        // force-complete after a generous timeout to prevent UI deadlock.
        Task { @MainActor in
            try? await Task.sleep(for: flingSafetyNetTimeout)
            completeFling("safetyNet")
            // Always close the wide window here (the safety Task runs regardless of
            // whether completeFling skipped) → 800ms frame trace spanning fling +
            // reinit storm.
            PerfLog.review.stopFrameSampler("settle.frames")
        }
    }
}
