import SwiftUI
import SwiftData

@Observable @MainActor
final class TodayReviewState {
    struct SubmittedAnswer {
        let feedback: ReviewFeedback
        let answeredAt: Date
        let reviewRecordID: UUID
    }

    // MARK: - Card Navigation

    var queue: [VocabularyEntry]
    private var queuePersistenceIDs: [String]
    private var queueBaselines: [TodayReviewSessionSnapshotStore.ReviewBaseline]
    var currentIndex = 0
    var revealStage: TodayReviewRevealStage = .front
    var linkedCardStack: [VocabularyEntry] = []
    var tappedLink: KGCardLinkSummary?
    var preparedCardCache: [UUID: TodayReviewPresenterState.CurrentCard] = [:]

    // MARK: - Delegated concerns

    let scoring = ReviewScoringState()

    // MARK: - Scoring (forwarded projections — keep external API stable)

    var submittedAnswers: [Int: SubmittedAnswer] { scoring.submittedAnswers }
    var rememberedFeedbackTrigger: Int { scoring.rememberedFeedbackTrigger }
    var forgotFeedbackTrigger: Int { scoring.forgotFeedbackTrigger }
    var forgotCount: Int { scoring.forgotCount }
    var rememberedCount: Int { scoring.rememberedCount }

    // MARK: - Autoplay
    // NOTE: autoplay is kept here because its loop body directly mutates
    // navigation state (currentIndex, revealStage). Extracting it would
    // require bidirectional coupling — less safe than keeping it co-located.

    var isAutoPlaying = false
    var isAutoPlayPaused = false
    var autoplayTask: Task<Void, Never>?

    // MARK: - Analytics

    let sessionStartTime: Date

    // MARK: - Immutable Lookup

    let linkedEntryLookup: [String: VocabularyEntry]
    let currentUserID: String?

    // MARK: - Init

    init(entries: [VocabularyEntry], allEntries: [VocabularyEntry], currentUserID: String?) {
        self.currentUserID = currentUserID
        let ordered = ReviewSessionStore.loadOrder(availableEntries: entries) ?? entries
        let restored = ReviewSessionPersistence.restoreSnapshotIfPossible(
            orderedEntries: ordered,
            userId: currentUserID
        )
        queue = ordered
        queuePersistenceIDs = ordered.map(ReviewSessionPersistence.persistenceID(for:))
        queueBaselines = ordered.map(ReviewSessionPersistence.makeBaseline(from:))
        sessionStartTime = restored?.sessionStartTime ?? Date()
        linkedEntryLookup = Self.buildLinkedEntryLookup(from: allEntries)
        if let restored {
            queue = restored.queue
            queuePersistenceIDs = restored.persistenceIDs
            queueBaselines = restored.baselines
            currentIndex = restored.currentIndex
            scoring.restore(
                submittedAnswers: restored.submittedAnswers,
                rememberedCount: restored.rememberedCount,
                forgotCount: restored.forgotCount
            )
        }
        if let first = queue.first {
            preparedCardCache = Self.buildPreparedCardCache(from: [first])
        }
        AppAnalytics.track(.reviewSessionStarted(cardCount: ordered.count))
        // Build remaining cards asynchronously to avoid blocking main thread
        if queue.count > 1 {
            Task { @MainActor in
                let fullCache = Self.buildPreparedCardCache(from: self.queue)
                self.preparedCardCache = fullCache
            }
        }
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
            isAutoPlaying: isAutoPlaying,
            isAutoPlayPaused: isAutoPlayPaused
        )
    }

    private var currentCardState: TodayReviewPresenterState.CurrentCard? {
        guard let current = currentEntry else { return nil }
        return cachedOrBuildCard(for: current)
    }

    private var nextCardState: TodayReviewPresenterState.CurrentCard? {
        let nextIndex = currentIndex + 1
        guard nextIndex < queue.count else { return nil }
        return cachedOrBuildCard(for: queue[nextIndex])
    }

    /// Fallback: build on-demand if async cache hasn't completed yet.
    private func cachedOrBuildCard(for entry: VocabularyEntry) -> TodayReviewPresenterState.CurrentCard? {
        if let cached = preparedCardCache[entry.id] { return cached }
        let built = Self.buildPreparedCardCache(from: [entry])
        if let card = built[entry.id] {
            preparedCardCache[entry.id] = card
            return card
        }
        return nil
    }

    // MARK: - Actions

    func handleLinkTap(_ link: KGCardLinkSummary) {
        tappedLink = link
    }

    func navigateToLinkedCard(link: KGCardLinkSummary) {
        guard let target = linkedEntryLookup[link.cardId] else { return }
        tappedLink = nil
        linkedCardStack.append(target)
    }

    func hideLink(_ link: KGCardLinkSummary) {
        tappedLink = nil
        guard let entry = currentEntry else { return }
        entry.mutateLink(id: link.id) { $0.withHidden(true) }
        linkedEntryLookup[link.cardId]?.mutateLink(id: link.id) { $0.withHidden(true) }
        rebuildCacheForEntry(entry)
    }

    func rebuildCacheForEntry(_ entry: VocabularyEntry) {
        let card = CardPresentation(entry: entry)
        let compactGroups = card.activeLinkGroups.map { fullGroup in
            let limited = fullGroup.limited(to: 2)
            return TodayReviewPresenterState.LinkGroup(
                id: fullGroup.id,
                label: fullGroup.label,
                items: limited.items,
                overflowCount: limited.overflowed(relativeToFullGroup: fullGroup)
            )
        }
        let backDoc = card.document.reviewBackSubset()
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(backDoc)
        preparedCardCache[entry.id] = .init(
            card: card,
            linkGroups: compactGroups,
            backDocument: backDoc,
            postExampleMetrics: metrics
        )
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
        syncQueueMetadata()
        ReviewSessionStore.saveOrder(queue.map(\.id))
        persistSnapshot()
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
        persistSnapshot()
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
        persistSnapshot()
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

    // MARK: - Submit (Scoring only — persistence deferred to session end)

    func submit(
        _ feedback: ReviewFeedback,
        container: ModelContainer,
        reviewSettings: ReviewSettings,
        onSaveFailure: (@MainActor @Sendable () -> Void)? = nil
    ) {
        guard currentEntry != nil else { return }
        if scoring.hasAnswer(at: currentIndex) {
            advancePastAlreadyScoredCard()
            return
        }

        scoring.record(feedback, at: currentIndex)

        AppAnalytics.track(.reviewCardSubmitted(
            feedback: feedback == .remembered ? "remembered" : "forgot",
            cardIndex: currentIndex,
            totalCards: queue.count
        ))

        ReviewSessionPersistence.flushSubmittedAnswer(
            at: currentIndex,
            queuePersistenceIDs: queuePersistenceIDs,
            queueBaselines: queueBaselines,
            submittedAnswers: scoring.submittedAnswers,
            container: container,
            reviewSettings: reviewSettings,
            onSaveFailure: onSaveFailure
        )
        persistSnapshot()
        revealStage = .front
        currentIndex += 1

        if currentIndex >= queue.count {
            ReviewSessionStore.clear()
            clearSnapshot()
            let durationMs = Int(Date().timeIntervalSince(sessionStartTime) * 1000)
            AppAnalytics.track(.reviewSessionEnded(
                remembered: rememberedCount,
                forgot: forgotCount,
                completed: true,
                durationMs: durationMs
            ))
        }
    }

    func persistSnapshot() {
        guard let currentUserID else { return }
        ReviewSessionPersistence.persistSnapshot(
            userId: currentUserID,
            sessionStartTime: sessionStartTime,
            currentIndex: currentIndex,
            queueCount: queue.count,
            queuePersistenceIDs: queuePersistenceIDs,
            queueBaselines: queueBaselines,
            submittedAnswers: scoring.submittedAnswers
        )
    }

    func clearSnapshot() {
        ReviewSessionPersistence.clearSnapshot(for: currentUserID)
    }

    // MARK: - Cache Builders

    static func buildPreparedCardCache(
        from entries: [VocabularyEntry]
    ) -> [UUID: TodayReviewPresenterState.CurrentCard] {
        var cache: [UUID: TodayReviewPresenterState.CurrentCard] = [:]
        cache.reserveCapacity(entries.count)
        for entry in entries {
            let card = CardPresentation(entry: entry)
            let compactGroups = card.activeLinkGroups.map { fullGroup in
                let shuffled = fullGroup.shuffled()
                let limited = shuffled.limited(to: 2)
                return TodayReviewPresenterState.LinkGroup(
                    id: fullGroup.id,
                    label: fullGroup.label,
                    items: limited.items,
                    overflowCount: limited.overflowed(relativeToFullGroup: fullGroup)
                )
            }
            let backDoc = card.document.reviewBackSubset()
            let metrics = TodayReviewPresenterState.PostExampleMetrics.from(backDoc)
            cache[entry.id] = .init(
                card: card,
                linkGroups: compactGroups,
                backDocument: backDoc,
                postExampleMetrics: metrics
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

    private func syncQueueMetadata() {
        queuePersistenceIDs = queue.map(ReviewSessionPersistence.persistenceID(for:))
        queueBaselines = queue.map(ReviewSessionPersistence.makeBaseline(from:))
    }

    private func advancePastAlreadyScoredCard() {
        revealStage = .front
        if currentIndex < queue.count - 1 {
            currentIndex += 1
        }
        persistSnapshot()
    }
}
