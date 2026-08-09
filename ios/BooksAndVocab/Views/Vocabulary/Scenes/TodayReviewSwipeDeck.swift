import SwiftUI

private let flingSafetyNetTimeout: Duration = .milliseconds(800)

// MARK: - Swipe Deck (resident card slots + swipe gesture)

extension TodayReviewPresenter {

    // MARK: Resident Slots（Phase 4 — 三 slot 結構常駐，值驅動）

    /// depth-2 殼層：純裝飾常駐節點，**恆駐 depth-2 不升頂**（Phase 4）——
    /// fling 期間 underPreview 從 depth-2 升走時，殼層原地補位，深度堆疊
    /// 視覺零空窗。只在 i+3 存在（remainingCount >= 3）時可見，暗示第四層；
    /// 可見性翻面瞬間被 depth-2 的 underPreview 卡遮蔽 —— 該卡半透明
    /// （idle layer opacity ≈ 0.44）且 rotation 與殼層不同，仍有微量透出，
    /// 為已知取捨（量級遠小於修掉的 depth-1 整卡 pop；殘餘 hitch 候選點）。
    /// 卡不足以 opacity 0 隱藏，不做 `if` 結構移除 —— settle 幀不付 insert/remove。
    func deckDepthShell(height: CGFloat) -> some View {
        let effectiveDepth: CGFloat = 2
        let scale: CGFloat = 1.0 - effectiveDepth * TodayReviewCardSlotLayout.stackDepthScaleStep
        let yOff: CGFloat = effectiveDepth * TodayReviewCardSlotLayout.stackDepthYStep
        let rotation = deckShellRotation
        let opacity = state.remainingCount >= 3 ? 0.35 : 0

        return AppRoundedRect(roundness: appSkin.roundness.card)
            .fill(appSkin.palette.cardBackground)
            .overlay(
                AppRoundedRect(roundness: appSkin.roundness.card)
                    .stroke(appSkin.palette.cardBorder.opacity(TodayReviewMetrics.cardBorderOpacity), lineWidth: 1)
            )
            .appElevation(.z1)
            .frame(height: height)
            .scaleEffect(scale)
            .offset(y: yOff)
            .rotationEffect(.degrees(rotation), anchor: .center)
            .opacity(opacity)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }

    /// 固定 identity 的卡 slot — 完整卡骨架（frontFoldSurface + chrome +
    /// answerFold stub）永久存活於全尺寸；姿態 = `f(role, dismissProgress)`
    /// 純值（TodayReviewCardSlotLayout.transform）。promote 時只有 role 翻面
    /// （hit-testing / a11y / 邊框值 diff），無結構 diff。
    // TODO(A/B 量測): 舊 cardStackLayers 對 deck 預覽包 .drawingGroup(opaque:false)。
    // slot 常駐後保守先移除（rasterize 互動卡會改變 gesture/a11y/fold 渲染行為）;
    // 若 device probe 顯示 preview 合成成本回升，A=對非 active 的那張卡包一層
    // .drawingGroup、B=維持移除，以 settle.frames/fling.frames 對比定案。
    @ViewBuilder
    func cardSlotView(slot: Int, viewport: ReviewCardViewport) -> some View {
        if slot < state.slots.count, let content = state.slots[slot].card {
            let role = state.slots[slot].assignment.role
            let isActive = role == .active
            let transform = TodayReviewCardSlotLayout.transform(
                role: role,
                swipeOffset: isActive ? swipeOffset : 0,
                dismissProgress: dismissProgress,
                stackRotation: slot < stackRotations.count ? stackRotations[slot] : 0,
                screenWidth: screenWidth,
                introProgress: introProgress
            )
            let borderOpacity = TodayReviewCardSlotLayout.borderOpacity(role: role, dismissProgress: dismissProgress)
            let slotShowsAnswer = isActive && state.revealStage.showsAnswer
            let _ = { if role == .preview, dismissProgress > 0 || dismissPhase != .idle {
                PerfLog.review.mark(
                    "stack.preview",
                    "w=\(content.card.word) scale=\(String(format: "%.3f", transform.scale)) op=\(String(format: "%.2f", transform.opacity)) prog=\(String(format: "%.2f", dismissProgress))"
                )
            } }()

            // 一張完整的卡（正面摺頁 ＋ chrome ＋ 背面摺頁 ＋ 摺疊動畫）＝
            // `ReviewCardView`；牌堆只負責姿態與互動鎖。互動鎖由這裡算好再傳，
            // 卡片內部不判 dismiss 相位。
            ReviewCardView(
                content: content,
                profile: reviewCardLayoutStore.profile,
                viewport: viewport,
                showsAnswer: slotShowsAnswer,
                mountsBack: isActive && backContentMounted,
                interactive: isActive && isCardInteractive,
                borderOpacity: borderOpacity,
                collocationExplanations: collocationExplanations,
                actions: ReviewCardActions(
                    advanceReveal: onAdvanceReveal,
                    collapseReveal: onCollapseReveal,
                    detailTap: onDetailTap,
                    linkTap: onLinkTap,
                    addLink: onAddLink,
                    explainCollocation: onExplainCollocation,
                    viewCollocationExplanation: onViewCollocationExplanation,
                    deleteCollocationExplanation: onDeleteCollocationExplanation
                ),
                // FIX(review-flip-gap)：逐 slot 記實測 front 高度（active slot
                // 恆 uncap → 量到自然高度）。`activeCardHeight` 讀 active slot 的值，
                // 供非 active slot cap（見下方的 .frame）。量測只有卡片自己做得到，
                // 所以由它回吐；deck 這邊不再重覆量一次。
                onFrontHeightChange: { h in
                    guard slotFrontHeights.indices.contains(slot),
                          abs(slotFrontHeights[slot] - h) > 0.5 else { return }
                    slotFrontHeights[slot] = h
                }
            )
            // FIX(review-flip-gap)：非 active slot 的 layout 高度 cap 到 active 卡
            // 高度，讓 ZStack(alignment:.top) 只由 active 卡決定高度、不被較高的背景
            // 卡撐大。active slot 傳 nil（自然高度，反而定義 activeCardHeight）。
            // 這一步就修好 layout 縫隙（fixed frame 對 parent 恆報 activeCardHeight）。
            .frame(height: isActive ? nil : activeCardHeight, alignment: .top)
            // 內容溢出收斂：多數較高背景卡（如 production 長例句）會被 ReviewFoldSurface
            // 內部 .clipShape + cap frame 自然截斷、不溢出；但 fixedSize 內容（多行
            // recognition 長單字）會堅持自然高度而溢出 frame 往下渲染。統一 clip 掉
            // 非 active slot 超出 cap 的部分。active slot 給超大負 inset = 不裁切，
            // 保留卡片陰影（appElevation）。value-conditional 單一 modifier → 不破壞
            // Phase 4 常駐 slot 身分。
            .clipShape(Rectangle().inset(by: isActive ? -3000 : 0))
            .geometryGroup()
            #if DEBUG
            // gap 調查（slot 整體）：量整個 slot VStack 的 layout 高度（transform 前）。
            // 非 active slot 的 h 明顯 > active = 撐高 reviewCard ZStack、把 expand
            // zone 下推 → 使用者看到的縫隙。role/word 指認撐高者，answer 分量判 H1/H2。
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { h in
                logSlotGeometry(slot: slot, role: role, kind: "slot", word: content.card.word, height: h)
            }
            #endif
            .animation((dismissPhase == .idle && !suppressFoldAnimation) ? AppMotion.reviewRevealSpring : nil,
                       value: slotShowsAnswer)
            // 姿態 = 純值 diff（modifier 結構固定）。順序對齊舊雙軌：
            // scale → offset → rotation → opacity；rotation anchor 在 role 翻面
            // 時切換（active=.bottom / preview=.center），翻面瞬間角度恆 0，無跳動。
            .scaleEffect(transform.scale)
            .offset(x: transform.xOffset, y: transform.yOffset)
            .rotationEffect(.degrees(transform.rotationDegrees), anchor: isActive ? .bottom : .center)
            .opacity(transform.opacity)
            // zIndex 按 role 排深度（殼層預設 0 恆最底）。三 slot 制下不可用
            // 宣告順序當 tie-breaker：slot index 與深度的對應每次推進都在輪替。
            .zIndex(role == .active ? 3 : (role == .preview ? 2 : 1))
            // promote 的本體：hit-testing gate 翻面（preview 純裝飾不可點）。
            .allowsHitTesting(isActive)
            .accessibilityHidden(!isActive)
            .simultaneousGesture(swipeDragGesture)
        }
    }

    #if DEBUG
    /// Gap 調查儀器（DEBUG-only，RELEASE 零成本）。逐 slot 記 layout 高度，
    /// 供離線比對「非 active slot 是否比 active 高 → 撐高 reviewCard ZStack →
    /// 把 expand zone 下推 = 卡片與底部大縫隙」。
    /// - kind=slot：整個 slot VStack 的 layout 高度。
    /// - kind=answer：answer surface 經 frame(height:) clamp 後高度（front 應為 0）。
    /// 不 gate、附完整相位脈絡（reveal/dismiss/off/idx），離線 grep 過濾 settled front。
    func logSlotGeometry(slot: Int, role: TodayReviewCardSlotRole, kind: String, word: String, height: CGFloat) {
        PerfLog.review.mark(
            "gap.geom",
            "slot=\(slot) role=\(role) kind=\(kind) w=\(word) h=\(String(format: "%.1f", height)) reveal=\(state.revealStage.rawValue) dismiss=\(dismissPhase == .idle ? 0 : 1) off=\(Int(swipeOffset)) idx=\(state.progressText)"
        )
    }
    #endif

    // MARK: Swipe Gesture + Fling Animation

    var screenWidth: CGFloat { containerWidth }

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
                    frozenSwipeIntensity = 0
                    swipeOffset = 0
                    // 只重隨機被回收的舊 active slot（settle 後換內容、沉到
                    // depth-2）—— 存活的 preview/underPreview slot rotation 持久，
                    // 角色輪替跨 settle 連續不跳動。
                    if let recycled = state.slots.firstIndex(where: { $0.assignment.role == .active }),
                       recycled < stackRotations.count {
                        stackRotations[recycled] = .random(in: -1...1)
                    }
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
                    // promote（Phase 4）：callback() 推進 currentIndex → slot role
                    // 在本 no-anim transaction 內三向輪替。preview→active 與
                    // underPreview→preview 兩個存活 slot 的 transform 已被 fling
                    // 動畫推到目標值、內容 index 不變 → settle 幀零內容 diff；
                    // 唯一內容 diff 落在被回收、沉到 depth-2 的舊 active slot
                    // （被殼層位置遮蔽）。模型推進時序與舊雙軌完全相同
                    // （submit 仍在 fling 完成時刻，非樂觀預推）。
                    callback()
                    dismissPhase = .idle
                }
            }
            DispatchQueue.main.async {
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
