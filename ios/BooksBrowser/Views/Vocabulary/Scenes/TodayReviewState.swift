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

    // MARK: - Scoring

    var submittedAnswers: [Int: SubmittedAnswer] = [:]
    var rememberedFeedbackTrigger = 0
    var forgotFeedbackTrigger = 0
    private(set) var forgotCount = 0
    private(set) var rememberedCount = 0

    // MARK: - Autoplay

    var isAutoPlaying = false
    var isAutoPlayPaused = false
    var autoplayTask: Task<Void, Never>?

    // MARK: - Persistence

    // MARK: - Analytics

    let sessionStartTime: Date

    // MARK: - Immutable Lookup

    let linkedEntryLookup: [String: VocabularyEntry]
    let currentUserID: String?

    // MARK: - Init

    init(entries: [VocabularyEntry], allEntries: [VocabularyEntry], currentUserID: String?) {
        self.currentUserID = currentUserID
        let ordered = ReviewSessionStore.loadOrder(availableEntries: entries) ?? entries
        let restored = Self.restoreSnapshotIfPossible(
            orderedEntries: ordered,
            userId: currentUserID
        )
        queue = ordered
        queuePersistenceIDs = ordered.map(Self.persistenceID(for:))
        queueBaselines = ordered.map(Self.makeBaseline(from:))
        sessionStartTime = restored?.sessionStartTime ?? Date()
        linkedEntryLookup = Self.buildLinkedEntryLookup(from: allEntries)
        if let restored {
            queue = restored.queue
            queuePersistenceIDs = restored.persistenceIDs
            queueBaselines = restored.baselines
            currentIndex = restored.currentIndex
            submittedAnswers = restored.submittedAnswers
            rememberedCount = restored.rememberedCount
            forgotCount = restored.forgotCount
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
        reviewSettings: ReviewSettings
    ) {
        guard currentEntry != nil else { return }
        if submittedAnswers[currentIndex] != nil {
            advancePastAlreadyScoredCard()
            return
        }

        let answer = SubmittedAnswer(
            feedback: feedback,
            answeredAt: Date(),
            reviewRecordID: UUID()
        )
        submittedAnswers[currentIndex] = answer
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

        flushSubmittedAnswer(
            at: currentIndex,
            container: container,
            reviewSettings: reviewSettings
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
        guard !queue.isEmpty else {
            TodayReviewSessionSnapshotStore.clear(for: currentUserID)
            return
        }

        let submissions = submittedAnswers.mapValues { answer in
            TodayReviewSessionSnapshotStore.Snapshot.SubmittedAnswer(
                feedbackRaw: answer.feedback.rawValue,
                answeredAt: answer.answeredAt,
                reviewRecordID: answer.reviewRecordID
            )
        }
        let queueItems = zip(queuePersistenceIDs, queueBaselines).map { persistenceID, baseline in
            TodayReviewSessionSnapshotStore.Snapshot.QueueItem(
                persistenceID: persistenceID,
                baseline: baseline
            )
        }

        TodayReviewSessionSnapshotStore.save(.init(
            userId: currentUserID,
            sessionStartTime: sessionStartTime,
            currentIndex: min(currentIndex, queue.count),
            queue: queueItems,
            submissions: submissions,
            updatedAt: Date()
        ))
    }

    func clearSnapshot() {
        TodayReviewSessionSnapshotStore.clear(for: currentUserID)
    }

    // MARK: - Background Persistence (idempotent per answer)

    func flushSubmittedAnswer(
        at index: Int,
        container: ModelContainer,
        reviewSettings: ReviewSettings
    ) {
        guard index < queuePersistenceIDs.count,
              index < queueBaselines.count,
              let answer = submittedAnswers[index] else { return }

        let persistenceID = queuePersistenceIDs[index]
        let baseline = queueBaselines[index]
        Task.detached(priority: .utility) {
            let ctx = ModelContext(container)
            guard let entry = try? Self.fetchEntry(for: persistenceID, in: ctx) else { return }

            Self.applySubmittedAnswer(
                answer,
                baseline: baseline,
                to: entry,
                reviewSettings: reviewSettings
            )

            if (try? Self.fetchReviewRecord(id: answer.reviewRecordID, in: ctx)) == nil {
                let record = ReviewRecord(
                    word: entry.word,
                    entryID: entry.id,
                    feedback: answer.feedback.rawValue,
                    reviewedAt: answer.answeredAt
                )
                record.id = answer.reviewRecordID
                record.notebookId = entry.notebookId
                ctx.insert(record)
            }

            if !ctx.safeSave() {
                AppLog.data.error("flushSubmittedAnswer: failed to save review result for \(entry.word)")
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
        queuePersistenceIDs = queue.map(Self.persistenceID(for:))
        queueBaselines = queue.map(Self.makeBaseline(from:))
    }

    private func advancePastAlreadyScoredCard() {
        revealStage = .front
        if currentIndex < queue.count - 1 {
            currentIndex += 1
        }
        persistSnapshot()
    }

    private static func persistenceID(for entry: VocabularyEntry) -> String {
        if let kgCardId = entry.kgCardId, !kgCardId.isEmpty {
            return "kg:\(kgCardId)"
        }
        return "local:\(entry.id.uuidString)"
    }

    private static func makeBaseline(
        from entry: VocabularyEntry
    ) -> TodayReviewSessionSnapshotStore.ReviewBaseline {
        .init(
            reviewIntervalHours: entry.reviewIntervalHours,
            nextReviewAt: entry.nextReviewAt,
            lastReviewedAt: entry.lastReviewedAt,
            reviewCount: entry.reviewCount,
            lapseCount: entry.lapseCount,
            reviewStreak: entry.reviewStreak,
            lastReviewFeedbackRaw: entry.lastReviewFeedbackRaw
        )
    }

    nonisolated private static func fetchEntry(
        for persistenceID: String,
        in context: ModelContext
    ) throws -> VocabularyEntry? {
        if persistenceID.hasPrefix("kg:") {
            let kgCardID = String(persistenceID.dropFirst(3))
            var descriptor = FetchDescriptor<VocabularyEntry>(
                predicate: #Predicate<VocabularyEntry> { $0.kgCardId == kgCardID }
            )
            descriptor.fetchLimit = 1
            return try context.fetch(descriptor).first
        }

        guard persistenceID.hasPrefix("local:"),
              let rawID = persistenceID.split(separator: ":", maxSplits: 1).last,
              let entryID = UUID(uuidString: String(rawID)) else {
            return nil
        }

        var descriptor = FetchDescriptor<VocabularyEntry>(
            predicate: #Predicate<VocabularyEntry> { $0.id == entryID }
        )
        descriptor.fetchLimit = 1
        return try context.fetch(descriptor).first
    }

    nonisolated private static func fetchReviewRecord(id: UUID, in context: ModelContext) throws -> ReviewRecord? {
        var descriptor = FetchDescriptor<ReviewRecord>(
            predicate: #Predicate<ReviewRecord> { $0.id == id }
        )
        descriptor.fetchLimit = 1
        return try context.fetch(descriptor).first
    }

    nonisolated private static func applySubmittedAnswer(
        _ answer: SubmittedAnswer,
        baseline: TodayReviewSessionSnapshotStore.ReviewBaseline,
        to entry: VocabularyEntry,
        reviewSettings: ReviewSettings
    ) {
        let minInterval = reviewSettings.effectiveMinimumIntervalHours
        let baseInterval = baseline.reviewCount == 0
            ? reviewSettings.effectiveInitialIntervalHours
            : max(baseline.reviewIntervalHours, minInterval)
        let updatedInterval = VocabularyReviewPolicy.nextIntervalHours(
            currentIntervalHours: baseInterval,
            feedback: answer.feedback,
            settings: reviewSettings
        )

        entry.reviewIntervalHours = updatedInterval
        entry.nextReviewAt = answer.answeredAt.addingTimeInterval(updatedInterval * 3600)
        entry.lastReviewedAt = answer.answeredAt
        entry.reviewCount = baseline.reviewCount + 1
        entry.lastReviewFeedbackRaw = answer.feedback.rawValue
        switch answer.feedback {
        case .remembered:
            entry.reviewStreak = baseline.reviewStreak + 1
            entry.lapseCount = baseline.lapseCount
        case .forgot:
            entry.reviewStreak = 0
            entry.lapseCount = baseline.lapseCount + 1
        }
    }

    private static func restoreSnapshotIfPossible(
        orderedEntries: [VocabularyEntry],
        userId: String?
    ) -> (
        queue: [VocabularyEntry],
        persistenceIDs: [String],
        baselines: [TodayReviewSessionSnapshotStore.ReviewBaseline],
        currentIndex: Int,
        submittedAnswers: [Int: SubmittedAnswer],
        rememberedCount: Int,
        forgotCount: Int,
        sessionStartTime: Date
    )? {
        guard let userId,
              let snapshot = TodayReviewSessionSnapshotStore.load(for: userId) else {
            return nil
        }

        let entryMap = Dictionary(uniqueKeysWithValues: orderedEntries.map { (persistenceID(for: $0), $0) })
        let restoredQueue = snapshot.queue.compactMap { entryMap[$0.persistenceID] }
        guard restoredQueue.count == snapshot.queue.count else {
            TodayReviewSessionSnapshotStore.clear(for: userId)
            return nil
        }

        let restoredIDs = snapshot.queue.map(\.persistenceID)
        let restoredIDSet = Set(restoredIDs)
        let appendedEntries = orderedEntries.filter { !restoredIDSet.contains(persistenceID(for: $0)) }
        let queue = restoredQueue + appendedEntries
        let persistenceIDs = restoredIDs + appendedEntries.map(persistenceID(for:))
        let baselines = snapshot.queue.map(\.baseline) + appendedEntries.map(makeBaseline(from:))

        var submittedAnswers: [Int: SubmittedAnswer] = [:]
        var rememberedCount = 0
        var forgotCount = 0
        for (index, answer) in snapshot.submissions {
            guard index < queue.count,
                  let feedback = ReviewFeedback(rawValue: answer.feedbackRaw) else { continue }
            submittedAnswers[index] = SubmittedAnswer(
                feedback: feedback,
                answeredAt: answer.answeredAt,
                reviewRecordID: answer.reviewRecordID
            )
            if feedback == .remembered { rememberedCount += 1 } else { forgotCount += 1 }
        }

        return (
            queue: queue,
            persistenceIDs: persistenceIDs,
            baselines: baselines,
            currentIndex: min(snapshot.currentIndex, queue.count),
            submittedAnswers: submittedAnswers,
            rememberedCount: rememberedCount,
            forgotCount: forgotCount,
            sessionStartTime: snapshot.sessionStartTime
        )
    }
}
