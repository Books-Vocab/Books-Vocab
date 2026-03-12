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
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore

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
    @State private var preparedCardCache: [UUID: TodayReviewPresenterState.CurrentCard] = [:]
    @State private var isAutoPlaying = false
    @State private var isAutoPlayPaused = false
    @State private var autoplayTask: Task<Void, Never>?

    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager

    private let linkedEntryLookup: [String: VocabularyEntry]
    let onClose: () -> Void

    init(entries: [VocabularyEntry], allEntries: [VocabularyEntry], onClose: @escaping () -> Void) {
        let ordered = ReviewSessionStore.loadOrder(availableEntries: entries) ?? entries
        _queue = State(initialValue: ordered)
        _preparedCardCache = State(initialValue: Self.buildPreparedCardCache(from: ordered))
        linkedEntryLookup = Self.buildLinkedEntryLookup(from: allEntries)
        self.onClose = onClose
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
        return preparedCardCache[queue[nextIndex].id]
    }

    private var currentCardState: TodayReviewPresenterState.CurrentCard? {
        guard let current = currentEntry else { return nil }
        return preparedCardCache[current.id]
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
        guard let target = linkedEntryLookup[link.cardId] else { return }
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
    /// SwiftData 變動延後到 fling 尾段完全落地後，避免主線程在動畫尾幀做資料更新。
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

        // 真正延後 model mutation，避免 fling 尾段撞上 SwiftData 變動與存取追蹤。
        let entryToUpdate = current
        let settings = reviewSettingsStore.settings
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(280))
            entryToUpdate.applyReviewFeedback(feedback, settings: settings)
            ReviewActivityLog.recordReview(
                word: entryToUpdate.word,
                entryID: entryToUpdate.id,
                feedback: feedback,
                context: modelContext
            )
        }

        // 延後 save，合併連續 review 的寫入。
        pendingSaveTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(650))
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

    private static func buildPreparedCardCache(
        from entries: [VocabularyEntry]
    ) -> [UUID: TodayReviewPresenterState.CurrentCard] {
        var cache: [UUID: TodayReviewPresenterState.CurrentCard] = [:]
        cache.reserveCapacity(entries.count)
        for entry in entries {
            let card = CardPresentation(entry: entry)
            let compactGroups = card.linkGroups.map { fullGroup in
                let limited = fullGroup.limited(to: 2)
                return TodayReviewPresenterState.LinkGroup(
                    id: fullGroup.id,
                    label: fullGroup.label,
                    items: limited.items,
                    overflowCount: limited.overflowed(relativeToFullGroup: fullGroup)
                )
            }
            cache[entry.id] = .init(card: card, linkGroups: compactGroups)
        }
        return cache
    }

    private static func buildLinkedEntryLookup(
        from entries: [VocabularyEntry]
    ) -> [String: VocabularyEntry] {
        entries.reduce(into: [String: VocabularyEntry]()) { lookup, entry in
            guard let cardID = entry.kgCardId else { return }
            lookup[cardID] = entry
        }
    }
}
