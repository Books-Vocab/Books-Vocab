import SwiftData
import Foundation

/// 隔離所有 session 的資料庫操作與 UserDefaults 快照持久化。
/// 無 UI 依賴、無導航狀態依賴。
enum ReviewSessionPersistence {

    // MARK: - PersistenceID helpers

    static func persistenceID(for entry: VocabularyEntry) -> String {
        if let kgCardId = entry.kgCardId, !kgCardId.isEmpty {
            return "kg:\(kgCardId)"
        }
        return "local:\(entry.id.uuidString)"
    }

    static func makeBaseline(
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

    // MARK: - Snapshot (UserDefaults)

    static func persistSnapshot(
        userId: String,
        sessionStartTime: Date,
        currentIndex: Int,
        queueCount: Int,
        queuePersistenceIDs: [String],
        queueBaselines: [TodayReviewSessionSnapshotStore.ReviewBaseline],
        submittedAnswers: [Int: TodayReviewState.SubmittedAnswer]
    ) {
        guard !queuePersistenceIDs.isEmpty else {
            TodayReviewSessionSnapshotStore.clear(for: userId)
            return
        }

        let submissions = submittedAnswers.mapValues { answer in
            TodayReviewSessionSnapshotStore.Snapshot.SubmittedAnswer(
                feedbackRaw: answer.feedback.rawValue,
                answeredAt: answer.answeredAt,
                reviewRecordID: answer.reviewRecordID,
                flushed: answer.flushed
            )
        }
        let queueItems = zip(queuePersistenceIDs, queueBaselines).map { persistenceID, baseline in
            TodayReviewSessionSnapshotStore.Snapshot.QueueItem(
                persistenceID: persistenceID,
                baseline: baseline
            )
        }

        TodayReviewSessionSnapshotStore.save(.init(
            userId: userId,
            sessionStartTime: sessionStartTime,
            currentIndex: min(currentIndex, queueCount),
            queue: queueItems,
            submissions: submissions,
            updatedAt: Date()
        ))
    }

    static func clearSnapshot(for userId: String?) {
        TodayReviewSessionSnapshotStore.clear(for: userId)
    }

    // MARK: - Snapshot restore

    struct RestoredSession {
        let queue: [VocabularyEntry]
        let persistenceIDs: [String]
        let baselines: [TodayReviewSessionSnapshotStore.ReviewBaseline]
        let currentIndex: Int
        let submittedAnswers: [Int: TodayReviewState.SubmittedAnswer]
        let rememberedCount: Int
        let forgotCount: Int
        let sessionStartTime: Date
    }

    static func restoreSnapshotIfPossible(
        orderedEntries: [VocabularyEntry],
        userId: String?
    ) -> RestoredSession? {
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

        var submittedAnswers: [Int: TodayReviewState.SubmittedAnswer] = [:]
        var rememberedCount = 0
        var forgotCount = 0
        for (index, answer) in snapshot.submissions {
            guard index < queue.count,
                  let feedback = ReviewFeedback(rawValue: answer.feedbackRaw) else { continue }
            submittedAnswers[index] = TodayReviewState.SubmittedAnswer(
                feedback: feedback,
                answeredAt: answer.answeredAt,
                reviewRecordID: answer.reviewRecordID,
                flushed: answer.flushed
            )
            if feedback == .remembered { rememberedCount += 1 } else { forgotCount += 1 }
        }

        return RestoredSession(
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

    // MARK: - DB flush (deferred to session end; batched into ONE save)

    /// Persist ALL un-flushed submitted answers in a SINGLE background context with
    /// ONE `safeSave()` → ONE main-context merge.
    ///
    /// The per-flip submit path deliberately does NOT write the store: a per-card
    /// save merges back into the main `ModelContext`, refetching `NotebookListView`'s
    /// `@Query<VocabularyEntry>` (~37ms) and re-rendering the review cover — a single
    /// ~130ms main-thread block that froze the next-card render (measured: the freeze
    /// aligned exactly with the background save's completion, not the in-memory
    /// throwaway). Deferring to dismiss removes every per-flip merge; crash safety is
    /// covered by the per-flip UserDefaults snapshot + restore reflush.
    ///
    /// Idempotent: skips answers whose `ReviewRecord` already exists. Reports the
    /// flushed indices on success so the caller can mark them + finalize the snapshot
    /// ONLY after the store actually has the data. The empty-pending case still calls
    /// `onFlushed([])` so callers can finalize without special-casing a no-op.
    static func flushPendingAnswers(
        queuePersistenceIDs: [String],
        queueBaselines: [TodayReviewSessionSnapshotStore.ReviewBaseline],
        submittedAnswers: [Int: TodayReviewState.SubmittedAnswer],
        container: ModelContainer,
        reviewSettings: ReviewSettings,
        onFlushed: (@MainActor @Sendable (_ indices: [Int]) -> Void)? = nil,
        onFailure: (@MainActor @Sendable () -> Void)? = nil
    ) {
        let pending = submittedAnswers.filter { !$0.value.flushed }
        guard !pending.isEmpty else {
            if let onFlushed { Task { @MainActor in onFlushed([]) } }
            return
        }
        Task.detached(priority: .utility) {
            let ctx = ModelContext(container)
            var staged: [Int] = []
            for (index, answer) in pending {
                guard index < queuePersistenceIDs.count, index < queueBaselines.count else { continue }
                guard let entry = try? fetchEntry(for: queuePersistenceIDs[index], in: ctx) else {
                    // Entry fetch failed (DB error) or entry missing — this answer
                    // can't be persisted; leave it un-flushed so the snapshot + restore
                    // reflush gets another chance instead of silently dropping it.
                    AppLog.data.error("flushPendingAnswers: entry not found for \(queuePersistenceIDs[index]), result not saved")
                    continue
                }
                stageAnswer(answer, baseline: queueBaselines[index], entry: entry, reviewSettings: reviewSettings, in: ctx)
                staged.append(index)
            }
            let saved = PerfLog.review.measure("flush.dbSaveBatch", "n=\(staged.count)") { ctx.safeSave() }.value
            if saved {
                let confirmed = staged
                if let onFlushed { await onFlushed(confirmed) }
            } else {
                AppLog.data.error("flushPendingAnswers: batch save failed for \(staged.count) answers")
                if let onFailure { await onFailure() }
            }
        }
    }

    /// Apply one answer's SRS mutation to `entry` and insert its `ReviewRecord`
    /// (idempotent on record existence) into `ctx`. Caller owns the single save.
    private static func stageAnswer(
        _ answer: TodayReviewState.SubmittedAnswer,
        baseline: TodayReviewSessionSnapshotStore.ReviewBaseline,
        entry: VocabularyEntry,
        reviewSettings: ReviewSettings,
        in ctx: ModelContext
    ) {
        applySubmittedAnswer(answer, baseline: baseline, to: entry, reviewSettings: reviewSettings)

        if (try? fetchReviewRecord(id: answer.reviewRecordID, in: ctx)) == nil {
            // 固化 kgCardId + SRS 前後快照(此刻 entry 還在手上,值全可得):
            // baseline=複習前,applySubmittedAnswer 後 entry=複習後。事件自包含,
            // 上報不再靠卡離場即退化的三段反查,研究也能逐筆還原學習曲線。
            let record = ReviewRecord(
                word: entry.word,
                entryID: entry.id,
                feedback: answer.feedback.rawValue,
                reviewedAt: answer.answeredAt,
                kgCardId: entry.kgCardId.flatMap { $0.isEmpty ? nil : $0 },
                intervalBefore: baseline.reviewIntervalHours,
                intervalAfter: entry.reviewIntervalHours,
                nextReviewBefore: baseline.nextReviewAt,
                nextReviewAfter: entry.nextReviewAt,
                reviewCountAfter: entry.reviewCount,
                streakAfter: entry.reviewStreak,
                lapseAfter: entry.lapseCount
            )
            record.id = answer.reviewRecordID
            record.notebookId = entry.notebookId
            ctx.insert(record)
        }
    }

    // MARK: - Private DB helpers

    private static func fetchEntry(
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

    private static func fetchReviewRecord(id: UUID, in context: ModelContext) throws -> ReviewRecord? {
        var descriptor = FetchDescriptor<ReviewRecord>(
            predicate: #Predicate<ReviewRecord> { $0.id == id }
        )
        descriptor.fetchLimit = 1
        return try context.fetch(descriptor).first
    }

    private static func applySubmittedAnswer(
        _ answer: TodayReviewState.SubmittedAnswer,
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
}
