import SwiftUI
import SwiftData
import os

struct TodayReviewSession: Identifiable {
    let id = UUID()
    let entries: [VocabularyEntry]
}

enum TodayReviewRevealStage: Int {
    case front
    case back

    var showsAnswer: Bool { self == .back }

    mutating func advance() {
        switch self {
        case .front: self = .back
        case .back: break
        }
    }

    mutating func retract() {
        switch self {
        case .front: break
        case .back: self = .front
        }
    }
}

struct TodayReviewView: View {
    @Environment(\.modelContext) private var modelContext
    @Query private var allEntries: [VocabularyEntry]
    @EnvironmentObject private var reviewSettingsStore: ReviewSettingsStore

    @State private var queue: [VocabularyEntry]
    @State private var currentIndex = 0
    @State private var revealStage: TodayReviewRevealStage = .front
    @State private var linkedCardStack: [VocabularyEntry] = []
    @State private var forgotCount = 0
    @State private var rememberedCount = 0
    @State private var rememberedFeedbackTrigger = 0
    @State private var forgotFeedbackTrigger = 0
    @State private var persistenceFailureTrigger = 0
    @State private var persistenceErrorMessage: String?
    @State private var pendingSaveTask: Task<Void, Never>?
    @State private var presentationCache: [UUID: CardPresentation] = [:]
    @State private var isAutoPlaying = false
    @State private var isAutoPlayPaused = false
    @State private var autoplayTask: Task<Void, Never>?

    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager

    let onClose: () -> Void

    init(entries: [VocabularyEntry], onClose: @escaping () -> Void) {
        let ordered = ReviewSessionStore.loadOrder(availableEntries: entries) ?? entries
        _queue = State(initialValue: ordered)
        self.onClose = onClose
        // 預算前 3 張卡的 CardPresentation，避免首次渲染時 JSON parse 阻塞
        var cache: [UUID: CardPresentation] = [:]
        for entry in ordered.prefix(3) {
            cache[entry.id] = CardPresentation(entry: entry)
        }
        _presentationCache = State(initialValue: cache)
    }

    var body: some View {
        TodayReviewPresenter(
            state: presenterState,
            onClose: onClose,
            onAdvanceReveal: advanceReveal,
            onCollapseReveal: retractReveal,
            onShuffle: shuffleQueue,
            onPrevious: goPrevious,
            onNext: goNext,
            onForgot: { submit(.forgot) },
            onRemembered: { submit(.remembered) },
            onLinkTap: handleLinkTap,
            onToggleAutoPlay: toggleAutoPlay,
            onToggleAutoPlayPause: toggleAutoPlayPause,
            onDetailTap: handleDetailTap
        )
        .overlay {
            LinkedCardOverlayStack(stack: $linkedCardStack)
        }
        .onDisappear {
            // 複習結束時推送複習狀態到 backend
            guard authManager.isLoggedIn, !authManager.isDemoMode else { return }
            Task {
                await kgService.pushReviewQuietly(container: modelContext.container)
            }
        }
    }

    // MARK: - State Projection

    private var presenterState: TodayReviewPresenterState {
        TodayReviewPresenterState(
            progressText: progressText,
            currentCard: currentCardState,
            nextCard: nextCardState,
            revealStage: revealStage,
            canShuffle: queue.count - currentIndex > 1,
            canGoPrevious: currentIndex > 0,
            canGoNext: currentIndex < queue.count - 1,
            remainingCount: max(queue.count - currentIndex - 1, 0),
            forgotCount: forgotCount,
            rememberedCount: rememberedCount,
            rememberedFeedbackTrigger: rememberedFeedbackTrigger,
            forgotFeedbackTrigger: forgotFeedbackTrigger,
            persistenceFailureTrigger: persistenceFailureTrigger,
            persistenceErrorMessage: persistenceErrorMessage,
            isAutoPlaying: isAutoPlaying,
            isAutoPlayPaused: isAutoPlayPaused
        )
    }

    private var nextCardState: TodayReviewPresenterState.CurrentCard? {
        let nextIndex = currentIndex + 1
        guard nextIndex < queue.count else { return nil }
        return .init(card: cachedPresentation(for: queue[nextIndex]), linkGroups: [])
    }

    private func cachedPresentation(for entry: VocabularyEntry) -> CardPresentation {
        presentationCache[entry.id] ?? CardPresentation(entry: entry)
    }

    private func warmUpcomingCards() {
        let end = min(currentIndex + 3, queue.count)
        for i in currentIndex..<end {
            let entry = queue[i]
            if presentationCache[entry.id] == nil {
                presentationCache[entry.id] = CardPresentation(entry: entry)
            }
        }
    }

    private var currentCardState: TodayReviewPresenterState.CurrentCard? {
        guard let current = currentEntry else { return nil }
        let card = cachedPresentation(for: current)
        let compactGroups = card.linkGroups.map { fullGroup in
            let limited = fullGroup.limited(to: 2)
            return TodayReviewPresenterState.LinkGroup(
                id: fullGroup.id,
                label: fullGroup.label,
                items: limited.items,
                overflowCount: limited.overflowed(relativeToFullGroup: fullGroup)
            )
        }
        return .init(card: card, linkGroups: compactGroups)
    }

    private var currentEntry: VocabularyEntry? {
        guard currentIndex < queue.count else { return nil }
        return queue[currentIndex]
    }

    private var progressText: String {
        "\(min(currentIndex + 1, queue.count)) / \(queue.count)"
    }

    // MARK: - Actions

    private func handleLinkTap(_ link: KGCardLinkSummary) {
        guard let target = allEntries.first(where: { $0.kgCardId == link.cardId }) else { return }
        linkedCardStack.append(target)
    }

    private func handleDetailTap() {
        guard let current = currentEntry else { return }
        linkedCardStack.append(current)
    }

    private func advanceReveal() {
        withAnimation(AppMotion.reviewRevealSpring) {
            revealStage.advance()
        }
    }

    private func retractReveal() {
        withAnimation(AppMotion.reviewRevealSpring) {
            revealStage.retract()
        }
    }

    private func shuffleQueue() {
        let remaining = queue.count - currentIndex
        guard remaining > 1 else { return }
        withAnimation(AppMotion.reviewNavigationSpring) {
            var tail = Array(queue[currentIndex...])
            tail.shuffle()
            queue.replaceSubrange(currentIndex..., with: tail)
            revealStage = .front
        }
        ReviewSessionStore.saveOrder(queue.map(\.id))
        Task { @MainActor in warmUpcomingCards() }
    }

    private func goPrevious() {
        guard currentIndex > 0 else { return }
        withAnimation(AppMotion.reviewNavigationSpring) {
            revealStage = .front
            currentIndex -= 1
        }
        if isAutoPlaying && !isAutoPlayPaused {
            startAutoPlayLoop()
        }
        Task { @MainActor in warmUpcomingCards() }
    }

    private func goNext() {
        guard currentIndex < queue.count - 1 else { return }
        withAnimation(AppMotion.reviewNavigationSpring) {
            revealStage = .front
            currentIndex += 1
        }
        if isAutoPlaying && !isAutoPlayPaused {
            startAutoPlayLoop()
        }
        Task { @MainActor in warmUpcomingCards() }
    }

    // MARK: - Autoplay

    private func toggleAutoPlay() {
        if isAutoPlaying {
            stopAutoPlay()
        } else {
            startAutoPlay()
        }
    }

    private func toggleAutoPlayPause() {
        isAutoPlayPaused.toggle()
        if !isAutoPlayPaused {
            startAutoPlayLoop()
        }
    }

    private func startAutoPlay() {
        isAutoPlaying = true
        isAutoPlayPaused = false
        startAutoPlayLoop()
    }

    private func stopAutoPlay() {
        autoplayTask?.cancel()
        autoplayTask = nil
        isAutoPlaying = false
        isAutoPlayPaused = false
    }

    private func startAutoPlayLoop() {
        autoplayTask?.cancel()
        autoplayTask = Task { @MainActor in
            while !Task.isCancelled && isAutoPlaying && !isAutoPlayPaused {
                guard currentIndex < queue.count else {
                    stopAutoPlay()
                    return
                }

                // 正面停留 2 秒
                if revealStage == .front {
                    try? await Task.sleep(for: .seconds(2))
                    guard !Task.isCancelled && isAutoPlaying && !isAutoPlayPaused else { return }
                    advanceReveal()
                }

                // 答案停留 4 秒
                try? await Task.sleep(for: .seconds(4))
                guard !Task.isCancelled && isAutoPlaying && !isAutoPlayPaused else { return }

                // 前進到下一張（不歸類）
                if currentIndex < queue.count - 1 {
                    withAnimation(AppMotion.reviewNavigationSpring) {
                        revealStage = .front
                        currentIndex += 1
                    }
                } else {
                    // 最後一張播完
                    stopAutoPlay()
                    return
                }
            }
        }
    }

    /// 歸類卡片：推進 index → 延後 SwiftData 寫入
    /// 所有動畫由 Presenter 的 flingCard 控制，此處不包 withAnimation。
    /// SwiftData 變動（applyReviewFeedback / insert ReviewRecord）延後至下一幀，
    /// 避免 @Query 重算和 JSON 解析阻塞動畫幀。
    private func submit(_ feedback: ReviewFeedback) {
        guard let current = currentEntry else { return }
        pendingSaveTask?.cancel()
        persistenceErrorMessage = nil

        // UI 計數器更新（輕量，同步）
        switch feedback {
        case .remembered:
            rememberedFeedbackTrigger += 1
            rememberedCount += 1
        case .forgot:
            forgotFeedbackTrigger += 1
            forgotCount += 1
        }

        // 推進卡片（同步 — presenterState 透過 cache 瞬間完成）
        revealStage = .front
        currentIndex += 1

        if currentIndex >= queue.count {
            ReviewSessionStore.clear()
        }

        // SwiftData 變動延後至動畫幀結束後，避免 @Query re-render 風暴
        let entryToUpdate = current
        let settings = reviewSettingsStore.settings
        Task { @MainActor in
            entryToUpdate.applyReviewFeedback(feedback, settings: settings)
            ReviewActivityLog.recordReview(
                word: entryToUpdate.word,
                entryID: entryToUpdate.id,
                feedback: feedback,
                context: modelContext
            )
            warmUpcomingCards()
        }

        // 延後 save — 防止 @Query 反覆重算
        pendingSaveTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(500))
            do {
                try modelContext.save()
            } catch {
                withAnimation(AppMotion.phaseChange) {
                    persistenceErrorMessage = L10n.format("複習結果尚未寫入本機：%@", error.localizedDescription)
                }
                persistenceFailureTrigger += 1
            }
        }
    }
}
