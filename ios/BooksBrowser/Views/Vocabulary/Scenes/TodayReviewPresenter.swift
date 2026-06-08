import SwiftUI
import Inject

// MARK: - State

struct TodayReviewPresenterState {
    struct LinkGroup: Identifiable {
        let id: String
        let label: String
        let items: [KGCardLinkSummary]
        let overflowCount: Int
    }

    /// Pre-computed layout metrics for blocks after the first `.example` in backDocument.
    /// Separates the gap-dependent count from fixed heights so `answerExampleRadius`
    /// doesn't need to iterate blocks every frame.
    struct PostExampleMetrics {
        /// Total fixed height from post-example blocks (excluding gap contributions).
        let fixedHeight: CGFloat
        /// Number of gap units needed (one per post-example block).
        let gapCount: Int

        func totalHeight(gap: CGFloat) -> CGFloat {
            fixedHeight + CGFloat(gapCount) * gap
        }

        /// Iterate backDocument blocks once, returning pre-computed metrics.
        static func from(_ backDoc: CardDocument) -> PostExampleMetrics {
            var fixedHeight: CGFloat = 0
            var gapCount = 0
            var seenExample = false
            for block in backDoc.blocks {
                switch block {
                case .example:
                    seenExample = true
                case .divider:
                    if seenExample { fixedHeight += AppMetrics.dividerThin; gapCount += 1 }
                case .meaning(let meaning):
                    if seenExample {
                        // fixedSize: 每段最多 3 行（lineLimit），多段累加
                        let lineCount = meaning.paragraphs.count * 3
                        fixedHeight += CGFloat(lineCount) * 22; gapCount += 1
                    }
                case .collocations(let items):
                    if seenExample {
                        let rows = max(1, (items.count + 1) / 2)
                        fixedHeight += CGFloat(rows) * 32; gapCount += 1
                    }
                default:
                    if seenExample { fixedHeight += 30; gapCount += 1 }
                }
            }
            return .init(fixedHeight: fixedHeight, gapCount: gapCount)
        }
    }

    struct CurrentCard {
        let card: CardPresentation
        let linkGroups: [LinkGroup]
        let backDocument: CardDocument
        /// Pre-computed post-example block metrics — avoids re-iterating blocks every frame.
        let postExampleMetrics: PostExampleMetrics
    }

    let progressText: String
    let currentCard: CurrentCard?
    let nextCard: CurrentCard?
    let revealStage: TodayReviewRevealStage
    let canShuffle: Bool
    let canGoPrevious: Bool
    let canGoNext: Bool
    let remainingCount: Int
    let forgotCount: Int
    let rememberedCount: Int
    let rememberedFeedbackTrigger: Int
    let forgotFeedbackTrigger: Int
    let isAutoPlaying: Bool
    let isAutoPlayPaused: Bool
    let autoplayProgress: Double
    let autoplaySpeed: AutoplaySpeed
    let autoplaySoundEnabled: Bool
}

// MARK: - Presenter

struct TodayReviewPresenter: View {
    @ObserveInjection private var inject
    // internal — extension files 需要存取
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.appSkin) var appSkin
    @Environment(\.dynamicTypeSize) var dynamicTypeSize
    @Environment(\.speechService) var speechService

    // 動畫狀態 — dismissPhase 是唯一的互動鎖
    @State var frozenSwipeIntensity: Double = 0
    @State var swipeOffset: CGFloat = 0
    @State var containerWidth: CGFloat = 393
    @State var dismissPhase: DismissPhase = .idle
    @State var suppressTransition = false
    @State var flingHapticTrigger = 0
    @State private var celebrationTriggered = false
    @State private var lastAutoplaySpokenCardKey: String?
    @State var stackRotations: [Double] = [
        .random(in: -1.0...1.0),
        .random(in: -1.0...1.0)
    ]

    // Back-content mount gate. Decoupled from `showsAnswer` so the heavy back
    // tree (CardDocumentView / CardRichTextRenderer / VocabTierLabel /
    // reviewLinkStrip) is NOT built while the FRONT card is shown (subtraction
    // probe — see answerFoldSurface), yet STAYS mounted through the whole collapse
    // fold. `showsAnswer` flips instantly but `PaperFoldModifier.progress`
    // interpolates 1→0 over the spring; unmounting on the instant flip would tear
    // the real content out at progress≈1 and fold an empty box. So: mount on the
    // rising edge (content appears under the opacity-0 cover of the opening fold),
    // and defer unmount to AFTER the spring settles on the falling edge.
    @State var backContentMounted = false
    // Generation token: cancels a pending deferred-unmount when the user
    // re-reveals before the collapse settles, or when the card advances.
    @State private var backMountGeneration = 0
    // Spring settle budget for reviewRevealSpring (response 0.42, damping 0.88).
    // Mirrors the 0.8s safety window the swipe deck uses for settle.frames.
    private static let revealSettleSeconds: Double = 0.85

    enum DismissPhase {
        case idle
        case animatingOut
    }

    let state: TodayReviewPresenterState
    let isHelpPresented: Bool
    let showFirstRunHint: Bool
    let onClose: () -> Void
    let onAdvanceReveal: () -> Void
    let onCollapseReveal: () -> Void
    let onShuffle: () -> Void
    let onPrevious: () -> Void
    let onNext: () -> Void
    let onForgot: () -> Void
    let onRemembered: () -> Void
    let onLinkTap: (KGCardLinkSummary) -> Void
    let onAddLink: () -> Void
    let onToggleAutoPlay: () -> Void
    let onToggleAutoPlayPause: () -> Void
    let onChangeAutoPlaySpeed: () -> Void
    let onToggleAutoPlaySound: () -> Void
    let onDetailTap: () -> Void
    let onToggleHelp: () -> Void
    let onExplainCollocation: (String) -> Void
    let onViewCollocationExplanation: (String) -> Void
    let onDeleteCollocationExplanation: (String) -> Void
    var collocationExplanations: [String: String] = [:]

    /// 給 extension 判斷能否互動
    var isCardInteractive: Bool {
        dismissPhase == .idle
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let currentCard = state.currentCard {
                    topBar

                    GeometryReader { geo in
                        VStack(spacing: 0) {
                            reviewCard(currentCard, availableHeight: geo.size.height)
                                .padding(.horizontal, TodayReviewMetrics.cardHorizontalInset)
                                .padding(.top, TodayReviewMetrics.cardTopInset)
                                .padding(.bottom, TodayReviewMetrics.cardBottomInset)

                            if state.revealStage == .front {
                                revealExpandZone(
                                    title: L10n.string("點一下展開"),
                                    minHeight: max(geo.size.height * TodayReviewMetrics.frontHeightRatio, 180),
                                    action: onAdvanceReveal
                                )
                                .allowsHitTesting(isCardInteractive)
                            }
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                    }

                    bottomToolbar
                } else {
                    completionState
                }
            }
            #if targetEnvironment(macCatalyst)
            .overlay {
                if isHelpPresented {
                    appSkin.palette.shadow.opacity(0.25)
                        .ignoresSafeArea()
                        .onTapGesture { onToggleHelp() }
                        .transition(.overlayFade)

                    shortcutHelpOverlay
                        .transition(.overlayFade)
                }
            }
            .animation(AppMotion.panelState, value: isHelpPresented)
            #endif
            .platformContentMaxWidth(for: LayoutMode(horizontalSizeClass: sizeClass))
            .vocabCanvasBackground()
            .platformHideNavigationBar()
            .onGeometryChange(for: CGFloat.self) { proxy in
                proxy.size.width
            } action: { newWidth in
                // 動畫進行中不更新，避免 truncateRadius 變化導致 view rebuild 中斷 transition
                guard dismissPhase == .idle, !state.revealStage.showsAnswer else { return }
                containerWidth = newWidth
            }
            .onChange(of: state.revealStage) { _, stage in
                guard stage.showsAnswer else { return }
                speakCurrentAutoplayCardIfNeeded()
            }
            .onChange(of: state.revealStage.showsAnswer, initial: true) { _, shows in
                updateBackContentMount(showsAnswer: shows)
            }
            .onChange(of: currentCardKey) { _, _ in
                // Card advanced (next / previous / shuffle / submit / autoplay-advance):
                // the answer subtree is structurally replaced via `.id(cardIdentity)`.
                // Drop the gate immediately so the NEW front card doesn't inherit a
                // mounted heavy back tree (would defeat the front-render subtraction
                // probe). Bump the generation so any pending deferred-unmount no-ops.
                backMountGeneration += 1
                backContentMounted = false
            }
            .onChange(of: state.progressText) { _, _ in
                lastAutoplaySpokenCardKey = nil
            }
            .sensoryFeedback(.impact(weight: .light), trigger: flingHapticTrigger)
            .animation(AppMotion.panelState, value: isHelpPresented)
        }
        .enableInjection()
    }

    /// Presenter-level identity for the active card. Mirrors `reviewCard`'s
    /// `cardIdentity` so the mount gate resets on the same boundary the subtree
    /// is rebuilt.
    private var currentCardKey: String {
        guard let card = state.currentCard?.card else { return "" }
        return "\(card.dateAdded.timeIntervalSinceReferenceDate)-\(card.word)"
    }

    /// Drive `backContentMounted` with a lagged falling edge so the collapse fold
    /// always folds the real back content (blocker: collapse regression), while
    /// keeping it unmounted on the front card (subtraction probe).
    ///
    /// - rising (front→back): mount synchronously — the content must exist as the
    ///   `PaperFoldModifier` opens (progress 0→1, opacity 0→1), so it builds under
    ///   the opacity-0 cover and reveals in-place. Also opens a `reveal.frames`
    ///   sampler so the operator can confirm the now-reveal-time back-tree build
    ///   doesn't drop frames (didn't move the hitch from front render to reveal).
    /// - falling (back→front, same card): KEEP mounted; defer unmount to after the
    ///   spring settles so progress 1→0 folds the real content. Generation-guarded
    ///   so a re-reveal mid-collapse cancels the unmount.
    private func updateBackContentMount(showsAnswer: Bool) {
        backMountGeneration += 1
        let generation = backMountGeneration
        if showsAnswer {
            backContentMounted = true
            #if DEBUG
            PerfLog.review.startFrameSampler("reveal.frames")
            Task { @MainActor in
                try? await Task.sleep(nanoseconds: UInt64(Self.revealSettleSeconds * 1_000_000_000))
                PerfLog.review.stopFrameSampler("reveal.frames")
            }
            #endif
        } else {
            // Defer unmount until the collapse fold finishes; re-reveal or card
            // advance bumps the generation and cancels this.
            Task { @MainActor in
                try? await Task.sleep(nanoseconds: UInt64(Self.revealSettleSeconds * 1_000_000_000))
                guard generation == backMountGeneration,
                      !state.revealStage.showsAnswer else { return }
                backContentMounted = false
            }
        }
    }

    private func speakCurrentAutoplayCardIfNeeded() {
        guard state.isAutoPlaying,
              state.autoplaySoundEnabled,
              let card = state.currentCard?.card
        else { return }
        let key = "\(card.dateAdded.timeIntervalSinceReferenceDate)-\(card.word)"
        guard key != lastAutoplaySpokenCardKey else { return }
        lastAutoplaySpokenCardKey = key
        speechService.speak(card.word)
    }

    // MARK: - Card

    func reviewCard(_ currentCard: TodayReviewPresenterState.CurrentCard, availableHeight: CGFloat) -> some View {
        let card = currentCard.card
        let cardIdentity = "review-card-\(card.dateAdded.timeIntervalSinceReferenceDate)-\(card.word)"
        let _ = PerfLog.render.tick(
            "todayReview.card.body",
            "chars=\(card.word.count) reveal=\(state.revealStage.rawValue) blocks=\(currentCard.backDocument.blocks.count)"
        )
        // 轉場合成追蹤：僅在轉場期間(fling 中或有 swipe offset)逐幀 mark 作用中
        // 互動卡片的單字 + 狀態機,對照 stack.preview / front.chrome 看 fling 期間
        // 究竟合成了哪一層、chrome 何時補上。idle 不觸發,避免 reveal 動畫洪流。
        if dismissPhase != .idle || swipeOffset != 0 {
            PerfLog.review.mark(
                "compose.active",
                "w=\(card.word) dismiss=\(dismissPhase == .idle ? "idle" : "out") supp=\(suppressTransition) off=\(Int(swipeOffset))"
            )
        }

        return ZStack(alignment: .top) {
            // 牌堆 — 不隨 .id() 銷毀重建
            cardStackLayers()
                .frame(height: frontCardHeight)

            // 互動卡片
            VStack(spacing: 0) {
                frontFoldSurface(card)
                    .overlay(alignment: .topTrailing) {
                        frontCardChrome(card, interactive: true)
                    }

                // 永遠存在於 view tree — 繞過 .id() + conditional insertion
                // 首次渲染不走 .transition() 的 SwiftUI 結構性限制。
                // PaperFoldModifier(Animatable) 直接驅動摺疊動畫。
                // frame(height:0) 使摺疊時不佔 layout 空間，
                // 但 minHeight 內部約束使 view 仍以完整尺寸渲染（fold 視覺正確）。
                answerFoldSurface(currentCard, availableHeight: availableHeight)
                    .padding(.top, TodayReviewMetrics.stackLayerMicroOffset)
                    .modifier(PaperFoldModifier(progress: state.revealStage.showsAnswer ? 1 : 0))
                    .frame(height: state.revealStage.showsAnswer ? nil : 0, alignment: .top)
                    .allowsHitTesting(state.revealStage.showsAnswer)
            }
            .geometryGroup()
            .animation(dismissPhase == .idle ? AppMotion.reviewRevealSpring : nil,
                       value: state.revealStage.showsAnswer)
            // Identity must describe the queue card only. Reveal state stays out
            // so flip/collapse never tears down the heavy card subtree.
            .id(cardIdentity)
            .transition(suppressTransition ? .identity : .reviewCardPromote)
            .offset(x: swipeOffset)
            .rotationEffect(
                .degrees(Double(swipeOffset) / screenWidth * TodayReviewMetrics.swipeMaxRotation),
                anchor: .bottom
            )
            .opacity(cardOpacity)
            .simultaneousGesture(swipeDragGesture)
            #if targetEnvironment(macCatalyst)
            .contentShape(Rectangle())
            .onTapGesture {
                guard isCardInteractive, state.revealStage == .front else { return }
                onAdvanceReveal()
            }
            #endif
        }
    }

    // MARK: - Completion / Expand Zone

    var completionState: some View {
        VStack(spacing: appSkin.metrics.cardBlockPadding) {
            Spacer()
            VocabEmptyStateContent(
                title: L10n.string("今天複習完成"),
                systemImage: "checkmark.circle",
                description: L10n.string("這一輪 session 的卡片都處理完了。"),
                guidanceText: L10n.string("明天再來複習新到期的單字"),
                symbolBounce: celebrationTriggered
            )
            .scaleEffect(celebrationTriggered ? 1 : 0.8)
            .opacity(celebrationTriggered ? 1 : 0)
            .onAppear {
                withAnimation(AppMotion.celebrationBounce) {
                    celebrationTriggered = true
                }
            }
            Button(L10n.string("返回單字本"), action: onClose)
                .buttonStyle(.ghost(appSkin.palette.primaryText))
            Spacer()
        }
        .padding(.horizontal, appSkin.metrics.cardBlockPadding)
        .sensoryFeedback(.success, trigger: celebrationTriggered)
    }

    func revealExpandZone(
        title: String,
        minHeight: CGFloat,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            VStack(spacing: 10) {
                Capsule(style: .continuous)
                    .fill(appSkin.palette.quaternaryTextFaint)
                    .frame(width: 56, height: 3)
                Text(title)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.quaternaryText.opacity(TodayReviewMetrics.dimTextOpacity))
            }
            .frame(maxWidth: .infinity)
            .frame(minHeight: minHeight, maxHeight: .infinity, alignment: .top)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
