import SwiftUI
import SwiftData

@Observable @MainActor
final class TodayReviewState {
    // MARK: - Card Navigation

    var queue: [VocabularyEntry]
    var currentIndex = 0
    var revealStage: TodayReviewRevealStage = .front
    var linkedCardStack: [VocabularyEntry] = []
    var tappedLink: KGCardLinkSummary?
    var preparedCardCache: [UUID: TodayReviewPresenterState.CurrentCard] = [:]

    // MARK: - Scoring

    var forgotCount = 0
    var rememberedCount = 0
    var rememberedFeedbackTrigger = 0
    var forgotFeedbackTrigger = 0

    // MARK: - Autoplay

    var isAutoPlaying = false
    var isAutoPlayPaused = false
    var autoplayTask: Task<Void, Never>?

    // MARK: - Persistence

    var pendingSaveTask: Task<Void, Never>?
    var persistenceFailureTrigger = 0
    var persistenceErrorMessage: String?

    // MARK: - Analytics

    let sessionStartTime = Date()

    // MARK: - Immutable Lookup

    let linkedEntryLookup: [String: VocabularyEntry]

    // MARK: - Init

    init(entries: [VocabularyEntry], allEntries: [VocabularyEntry]) {
        let ordered = ReviewSessionStore.loadOrder(availableEntries: entries) ?? entries
        queue = ordered
        preparedCardCache = Self.buildPreparedCardCache(from: ordered)
        linkedEntryLookup = Self.buildLinkedEntryLookup(from: allEntries)
        AppAnalytics.track(.reviewSessionStarted(cardCount: ordered.count))
    }

    // MARK: - Computed (State Projection)

    var currentEntry: VocabularyEntry? {
        guard currentIndex < queue.count else { return nil }
        return queue[currentIndex]
    }

    var progressText: String {
        "\(min(currentIndex + 1, queue.count)) / \(queue.count)"
    }

    var presenterState: TodayReviewPresenterState {
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

    private var currentCardState: TodayReviewPresenterState.CurrentCard? {
        guard let current = currentEntry else { return nil }
        return preparedCardCache[current.id]
    }

    private var nextCardState: TodayReviewPresenterState.CurrentCard? {
        let nextIndex = currentIndex + 1
        guard nextIndex < queue.count else { return nil }
        return preparedCardCache[queue[nextIndex].id]
    }

    // MARK: - Actions

    func handleLinkTap(_ link: KGCardLinkSummary) {
        tappedLink = link
    }

    func navigateToLinkedCard() {
        guard let link = tappedLink,
              let target = linkedEntryLookup[link.cardId] else { return }
        tappedLink = nil
        linkedCardStack.append(target)
    }

    func handleDetailTap() {
        guard let current = currentEntry else { return }
        linkedCardStack.append(current)
    }

    func advanceReveal() {
        revealStage.advance()
    }

    func retractReveal() {
        revealStage.retract()
    }

    func shuffleQueue() {
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

    func goPrevious() {
        guard currentIndex > 0 else { return }
        withAnimation(AppMotion.reviewNavigationSpring) {
            revealStage = .front
            currentIndex -= 1
        }
        if isAutoPlaying && !isAutoPlayPaused {
            startAutoPlayLoop()
        }
    }

    func goNext() {
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

    func toggleAutoPlay() {
        if isAutoPlaying {
            stopAutoPlay()
        } else {
            startAutoPlay()
        }
    }

    func toggleAutoPlayPause() {
        isAutoPlayPaused.toggle()
        if !isAutoPlayPaused {
            startAutoPlayLoop()
        }
    }

    func startAutoPlay() {
        isAutoPlaying = true
        isAutoPlayPaused = false
        startAutoPlayLoop()
    }

    func stopAutoPlay() {
        autoplayTask?.cancel()
        autoplayTask = nil
        isAutoPlaying = false
        isAutoPlayPaused = false
    }

    func startAutoPlayLoop() {
        autoplayTask?.cancel()
        autoplayTask = Task { @MainActor in
            while !Task.isCancelled && isAutoPlaying && !isAutoPlayPaused {
                guard currentIndex < queue.count else {
                    stopAutoPlay()
                    return
                }

                if revealStage == .front {
                    try? await Task.sleep(for: .seconds(2))
                    guard !Task.isCancelled && isAutoPlaying && !isAutoPlayPaused else { return }
                    advanceReveal()
                }

                try? await Task.sleep(for: .seconds(4))
                guard !Task.isCancelled && isAutoPlaying && !isAutoPlayPaused else { return }

                if currentIndex < queue.count - 1 {
                    withAnimation(AppMotion.reviewNavigationSpring) {
                        revealStage = .front
                        currentIndex += 1
                    }
                } else {
                    stopAutoPlay()
                    return
                }
            }
        }
    }

    // MARK: - Submit (Scoring + Persistence)

    func submit(
        _ feedback: ReviewFeedback,
        modelContext: ModelContext,
        reviewSettings: ReviewSettings
    ) {
        guard let current = currentEntry else { return }
        pendingSaveTask?.cancel()
        persistenceErrorMessage = nil

        switch feedback {
        case .remembered:
            rememberedFeedbackTrigger += 1
            rememberedCount += 1
        case .forgot:
            forgotFeedbackTrigger += 1
            forgotCount += 1
        }

        AppAnalytics.track(.reviewCardSubmitted(
            feedback: feedback == .remembered ? "remembered" : "forgot",
            cardIndex: currentIndex,
            totalCards: queue.count
        ))

        revealStage = .front
        currentIndex += 1

        if currentIndex >= queue.count {
            ReviewSessionStore.clear()
            let durationMs = Int(Date().timeIntervalSince(sessionStartTime) * 1000)
            AppAnalytics.track(.reviewSessionEnded(
                remembered: rememberedCount,
                forgot: forgotCount,
                completed: true,
                durationMs: durationMs
            ))
        }

        let entryToUpdate = current
        let settings = reviewSettings
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(280))
            entryToUpdate.applyReviewFeedback(feedback, settings: settings)
            ReviewActivityLog.recordReview(
                word: entryToUpdate.word,
                entryID: entryToUpdate.id,
                feedback: feedback,
                context: modelContext,
                notebookId: entryToUpdate.notebookId
            )
        }

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

    // MARK: - Cache Builders

    static func buildPreparedCardCache(
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
            let backDoc = card.document.reviewBackSubset()
            cache[entry.id] = .init(
                card: card,
                linkGroups: compactGroups,
                backDocument: backDoc
            )
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
