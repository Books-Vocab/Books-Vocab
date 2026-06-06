import SwiftUI
import SwiftData

@Observable @MainActor
final class TodayReviewState {
    struct SubmittedAnswer {
        let feedback: ReviewFeedback
        let answeredAt: Date
        let reviewRecordID: UUID
        /// Mirrors the snapshot flag: `true` once the background DB flush
        /// confirmed success. New answers start `false`; restore re-flushes any
        /// answer left `false`.
        var flushed: Bool = false
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
    static let cacheLookaheadLimit = 3

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
    var autoplaySpeed: AutoplaySpeed = ReviewSettingsStore.shared.settings.autoplaySpeed
    var autoplaySoundEnabled: Bool = ReviewSettingsStore.shared.settings.autoplaySoundEnabled

    // MARK: - Cache build
    // Keep only a small sliding window warm. Building hundreds of rich cards on
    // the main actor during session start causes visible hitches on large queues.
    private var cacheBuildTask: Task<Void, Never>?

    // MARK: - Analytics

    let sessionStartTime: Date

    // MARK: - Immutable Lookup

    let linkedEntryLookup: [String: VocabularyEntry]
    let currentUserID: String?

    // MARK: - Init

    init(entries: [VocabularyEntry], allEntries: [VocabularyEntry], currentUserID: String?) {
        self.currentUserID = currentUserID
        let ordered = ReviewSessionStore.loadOrder(
            availableEntries: entries,
            userID: currentUserID,
            // Today Review restores an unfinished queue even if sync added or removed cards
            // since the shuffle was saved; new cards are appended and missing cards filtered.
            allowPartialQueue: true
        ) ?? entries
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
        prewarmCardWindow()
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
            isAutoPlaying: isAutoPlaying,
            isAutoPlayPaused: isAutoPlayPaused,
            autoplayProgress: queue.isEmpty ? 0 : Double(currentIndex) / Double(queue.count),
            autoplaySpeed: autoplaySpeed,
            autoplaySoundEnabled: autoplaySoundEnabled
        )
    }

    private var currentCardState: TodayReviewPresenterState.CurrentCard? {
        guard let current = currentEntry else { return nil }
        return cachedOrBuildCard(for: current)
    }

    var currentCardForTesting: TodayReviewPresenterState.CurrentCard? {
        currentCardState
    }

    private var nextCardState: TodayReviewPresenterState.CurrentCard? {
        let nextIndex = currentIndex + 1
        guard nextIndex < queue.count else { return nil }
        return cachedOrBuildCard(for: queue[nextIndex])
    }

    var nextCardForTesting: TodayReviewPresenterState.CurrentCard? {
        nextCardState
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
        rebuildCacheForEntry(entry)
        // Bidirectional link target: if it lives in the review queue its
        // prepared-card cache is now stale too. VocabularyEntry is a class, so
        // match by identity. currentEntry (always in queue) is rebuilt above.
        if let target = linkedEntryLookup[link.cardId] {
            target.mutateLink(id: link.id) { $0.withHidden(true) }
            if target !== entry, queue.contains(where: { $0 === target }) {
                rebuildCacheForEntry(target)
            }
        }
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
        prewarmCardWindow()
        ReviewSessionStore.saveOrder(queue, userID: currentUserID)
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
        prewarmCardWindow()
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
        prewarmCardWindow()
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

    func changeAutoplaySpeed(to speed: AutoplaySpeed) {
        autoplaySpeed = speed
        var settings = ReviewSettingsStore.shared.settings
        settings.autoplaySpeed = speed
        ReviewSettingsStore.shared.update(settings)
        if isAutoPlaying && !isAutoPlayPaused {
            startAutoPlayLoop()
        }
    }

    func toggleAutoplaySound() {
        autoplaySoundEnabled.toggle()
        var settings = ReviewSettingsStore.shared.settings
        settings.autoplaySoundEnabled = autoplaySoundEnabled
        ReviewSettingsStore.shared.update(settings)
    }

    /// Cancel any background work tied to the session lifecycle. Called from the
    /// view's `onDisappear` so an early dismiss tears down the in-flight cache
    /// build instead of letting it run to completion and mutate state. Idempotent.
    func cancelBackgroundWork() {
        cacheBuildTask?.cancel()
        cacheBuildTask = nil
    }

    func startAutoPlayLoop() {
        autoplayTask?.cancel()
        autoplayTask = Task { @MainActor [weak self] in
            // [weak self] breaks the state → autoplayTask → closure → state
            // retain cycle. If state is deallocated mid-loop the guard exits
            // and the cancelled task tears down naturally.
            while !Task.isCancelled {
                guard let self, self.isAutoPlaying, !self.isAutoPlayPaused else { return }
                guard self.currentIndex < self.queue.count else {
                    self.stopAutoPlay()
                    return
                }

                if self.revealStage == .front {
                    try? await Task.sleep(for: self.autoplaySpeed.revealDelay)
                    guard !Task.isCancelled, self.isAutoPlaying, !self.isAutoPlayPaused else { return }
                    self.advanceReveal()
                }

                try? await Task.sleep(for: self.autoplaySpeed.stayDelay)
                guard !Task.isCancelled, self.isAutoPlaying, !self.isAutoPlayPaused else { return }

                if self.currentIndex < self.queue.count - 1 {
                    withAnimation(AppMotion.reviewNavigationSpring) {
                        self.revealStage = .front
                        self.currentIndex += 1
                    }
                    self.prewarmCardWindow()
                } else {
                    self.stopAutoPlay()
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

        let flushedIndex = currentIndex
        ReviewSessionPersistence.flushSubmittedAnswer(
            at: flushedIndex,
            queuePersistenceIDs: queuePersistenceIDs,
            queueBaselines: queueBaselines,
            submittedAnswers: scoring.submittedAnswers,
            container: container,
            reviewSettings: reviewSettings,
            onSaveFailure: onSaveFailure,
            onSaveSuccess: { [weak self] in
                // DB flush confirmed — mark the answer flushed and rewrite the
                // snapshot so a later restore won't re-flush it.
                self?.markAnswerFlushed(at: flushedIndex)
            }
        )
        persistSnapshot()
        revealStage = .front
        currentIndex += 1
        prewarmCardWindow()

        finishSessionIfComplete()
    }

    /// Session-completion teardown. Runs once `currentIndex` has advanced past
    /// the last card (`currentIndex >= queue.count`), at which point
    /// `currentEntry` is nil and the presenter shows `completionState`. Idempotent
    /// on the index check, but the side effects (clear / analytics) are NOT — only
    /// call this on the *transition* into completion (i.e. right after the index
    /// that advanced past the end). All paths that can reach the end-of-queue
    /// (normal final submit + repeated submit on the already-scored last card)
    /// funnel through here so the completion contract stays single-sourced.
    private func finishSessionIfComplete() {
        guard currentIndex >= queue.count else { return }
        ReviewSessionStore.clear(userID: currentUserID)
        clearSnapshot()
        let durationMs = Int(Date().timeIntervalSince(sessionStartTime) * 1000)
        AppAnalytics.track(.reviewSessionEnded(
            remembered: rememberedCount,
            forgot: forgotCount,
            completed: true,
            durationMs: durationMs
        ))
    }

    /// Re-run the DB flush for any restored answer whose previous flush never
    /// confirmed success (`flushed == false`). Fixes the consistency bug where a
    /// failed background flush left the card's spaced-repetition schedule stale
    /// while the snapshot still marked it answered — restore alone never
    /// re-flushed, so the schedule stayed broken forever.
    ///
    /// Idempotent: `flushSubmittedAnswer` skips DB writes when the
    /// ReviewRecord already exists, and the success callback flips the flag so a
    /// second call is a no-op. Safe to call on every appear.
    func reflushUnflushedRestoredAnswers(
        container: ModelContainer,
        reviewSettings: ReviewSettings,
        onSaveFailure: (@MainActor @Sendable () -> Void)? = nil
    ) {
        for (index, answer) in scoring.submittedAnswers where !answer.flushed {
            ReviewSessionPersistence.flushSubmittedAnswer(
                at: index,
                queuePersistenceIDs: queuePersistenceIDs,
                queueBaselines: queueBaselines,
                submittedAnswers: scoring.submittedAnswers,
                container: container,
                reviewSettings: reviewSettings,
                onSaveFailure: onSaveFailure,
                onSaveSuccess: { [weak self] in
                    self?.markAnswerFlushed(at: index)
                }
            )
        }
    }

    /// Flip an answer to flushed and rewrite the snapshot so a later restore
    /// won't re-flush it. Runs on the main actor (callback hops back from the
    /// detached flush task).
    private func markAnswerFlushed(at index: Int) {
        scoring.markFlushed(at: index)
        persistSnapshot()
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

    private func prewarmCardWindow() {
        guard !queue.isEmpty, currentIndex < queue.count else {
            preparedCardCache.removeAll(keepingCapacity: false)
            return
        }

        let start = max(currentIndex - 1, 0)
        let end = min(currentIndex + Self.cacheLookaheadLimit, queue.count - 1)
        let visibleEntries = Array(queue[start...end])
        let visibleIDs = Set(visibleEntries.map(\.id))

        preparedCardCache = preparedCardCache.filter { visibleIDs.contains($0.key) }

        let missingEntries = visibleEntries.filter { preparedCardCache[$0.id] == nil }
        guard !missingEntries.isEmpty else { return }
        preparedCardCache.merge(Self.buildPreparedCardCache(from: missingEntries)) { current, _ in current }
    }

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
        // Always advance, including past the last card: when the user
        // re-submits on an already-scored final card we must push currentIndex
        // to queue.count so currentEntry becomes nil and the session reaches its
        // completion state. Previously this guarded `< queue.count - 1`, which
        // pinned the last card forever and the completion teardown never ran.
        currentIndex += 1
        prewarmCardWindow()
        persistSnapshot()
        finishSessionIfComplete()
    }
}
