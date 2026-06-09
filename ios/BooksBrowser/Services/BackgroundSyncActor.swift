//
//  BackgroundSyncActor.swift
//  Books & Vocab
//
//  Created for safe off-main-thread SwiftData operations during sync.
//

import Foundation
import SwiftData

@ModelActor
actor BackgroundSyncActor {

    private static func parseISO8601(_ string: String) -> Date? {
        AppDateFormatters.parseISO8601(string)
    }

    /// Outcome of a `pullCardsToLocal` merge.
    ///
    /// `orphanCleanupBlocked` is `true` only when a FULL sync's orphan cleanup
    /// was skipped by the mass-deletion safety valve — meaning the local store
    /// still holds ghost entries the server no longer has. The caller must NOT
    /// advance the incremental boundary in that case, so the next sync runs a
    /// full sync again and retries the cleanup. It is always `false` for
    /// incremental syncs and for full syncs whose cleanup ran normally.
    struct PullResult: Sendable {
        var orphanCleanupBlocked: Bool
    }

    /// Fetch all cards from KG API and merge them into local SwiftData VocabularyEntry items
    /// This makes all KG words available offline (for underlining and browsing).
    @discardableResult
    func pullCardsToLocal(
        fetchedCards: [KGCard],
        isIncremental: Bool,
        progress: @Sendable @escaping (String, Int, Int) -> Void,
        notebookId: String = "default"
    ) throws -> PullResult {
        // Fetch all current local entries
        let descriptor = FetchDescriptor<VocabularyEntry>()
        let localEntries = try modelContext.fetch(descriptor)

        // Create a fast lookup dictionary keyed by (word, notebookId) to
        // correctly handle same word in different notebooks.
        var localDict = [String: VocabularyEntry]()
        for entry in localEntries {
            let key = mergeKey(entry.word, notebookId: entry.notebookId)
            localDict[key] = entry
        }

        // Keep track of fetched card keys to detect orphans later
        var fetchedCardKeys = Set<String>()

        // 1. Merge into local DB
        let totalCards = fetchedCards.count
        for (index, card) in fetchedCards.enumerated() {
            if index % 50 == 0 {
                progress(L10n.string("同步最新卡片..."), index, totalCards)
            }
            let cardNotebookId = card.notebookId ?? notebookId
            let mergeKey = mergeKey(card.content, notebookId: cardNotebookId)
            fetchedCardKeys.insert(mergeKey)

            if let existingEntry = localDict[mergeKey] {
                // Delete if marked as soft-deleted
                if card.isDeleted == true {
                    AppLog.sync.info("Remote soft-delete received: \(existingEntry.word)")
                    modelContext.delete(existingEntry)
                    continue
                }

                if existingEntry.syncAction == .delete {
                    // 本地標記為待刪除，不更新任何欄位，保留 syncStatus=0 讓 SyncView 可以 push
                } else {
                    // Update existing record
                    existingEntry.translation = card.meaning
                    existingEntry.partOfSpeech = card.pos
                    existingEntry.explanation = card.note
                    existingEntry.difficultyTier = card.difficultyTier
                    existingEntry.kgCardId = card.id
                    existingEntry.inflections = card.inflections ?? []
                    existingEntry.collocations = card.collocations ?? []
                    existingEntry.reviewMode = VocabularyCardMode(rawValue: card.mode) ?? .recognition
                    existingEntry.reviewExamples = card.examples
                    existingEntry.graphLinksByKind = card.linksByKind ?? [:]
                    existingEntry.isArchived = card.isArchived ?? false
                    if let cardNotebookId = card.notebookId {
                        existingEntry.notebookId = cardNotebookId
                    }
                    Self.applySource(from: card, into: existingEntry)
                    existingEntry.markSynced()

                    // Merge review state from server (server newer wins)
                    Self.mergeReviewState(from: card, into: existingEntry)
                }
            } else {
                // If it's softly deleted but we don't have it locally, ignore it
                if card.isDeleted == true { continue }

                // Create new record. Book title/chapter come from the
                // server `source` metadata (PR #533); fall back to a
                // placeholder only when `source` is absent or empty.
                let (bookTitle, chapterTitle) = Self.resolveSource(from: card)
                let newEntry = VocabularyEntry(
                    word: card.content,
                    translation: card.meaning,
                    context: card.examples.first ?? "",
                    explanation: card.note,
                    partOfSpeech: card.pos,
                    bookTitle: bookTitle,
                    chapterTitle: chapterTitle
                )
                newEntry.difficultyTier = card.difficultyTier
                newEntry.kgCardId = card.id
                newEntry.inflections = card.inflections ?? []
                newEntry.collocations = card.collocations ?? []
                newEntry.reviewMode = VocabularyCardMode(rawValue: card.mode) ?? .recognition
                newEntry.reviewExamples = card.examples
                newEntry.graphLinksByKind = card.linksByKind ?? [:]
                newEntry.isArchived = card.isArchived ?? false
                newEntry.notebookId = card.notebookId ?? notebookId
                newEntry.markSynced()

                // Apply server review state to new entry
                Self.mergeReviewState(from: card, into: newEntry)

                modelContext.insert(newEntry)
                localDict[mergeKey] = newEntry
            }
        }

        // 2. Cleanup orphans (Only for FULL sync)
        // Any local entry that has `syncStatus == 1` but is MISSING from the remote fetched list
        // means it was deleted remotely before soft-deletes were implemented.
        var orphanCleanupBlocked = false
        if !isIncremental {
            let localSyncedCount = localEntries.filter { $0.shouldAppearInKnowledgeList }.count
            let serverReturnedCount = fetchedCards.count

            // Safety guard: tiered protection against accidental mass deletion
            let ratio = Double(serverReturnedCount) / Double(max(localSyncedCount, 1))
            let diff = localSyncedCount - serverReturnedCount

            if ratio < 0.3 {
                orphanCleanupBlocked = true
                AppLog.sync.warning("Orphan cleanup BLOCKED: server returned <30% (\(serverReturnedCount)/\(localSyncedCount))")
            } else if diff > 50 && ratio < 0.8 {
                orphanCleanupBlocked = true
                AppLog.sync.warning("Orphan cleanup BLOCKED: large diff (\(diff) entries, ratio=\(String(format: "%.1f%%", ratio * 100)))")
            } else {
                progress(L10n.string("清理無效卡片..."), totalCards, totalCards)
                var orphanedWords: [String] = []
                for entry in localEntries {
                    guard entry.shouldAppearInKnowledgeList else { continue }
                    let orphanKey = mergeKey(entry.word, notebookId: entry.notebookId)
                    guard !fetchedCardKeys.contains(orphanKey) else { continue }
                    orphanedWords.append(entry.word)
                    modelContext.delete(entry)
                }
                if !orphanedWords.isEmpty {
                    AppLog.sync.warning("Orphan cleanup removed \(orphanedWords.count) entries: \(orphanedWords.prefix(20).joined(separator: ", "))\(orphanedWords.count > 20 ? "..." : "")")
                }
            }
        }

        try modelContext.save()
        AppLog.sync.info("pullCardsToLocal completed. Merged \(fetchedCards.count) remote cards.")
        return PullResult(orphanCleanupBlocked: orphanCleanupBlocked)
    }

    /// Deletes ALL per-user local SwiftData state — vocabulary, review records,
    /// notebooks, podcast (series / episode / progress), and books. This is the
    /// single local-cleanup entry point for logout and account switch, so it must
    /// cover every user-scoped @Model: leaving any model behind leaks account A's
    /// data into account B's session (e.g. followed podcast series + playback
    /// progress, and imported books with reading position/progress, survived the
    /// switch before this covered them).
    ///
    /// Scope: SwiftData @Model rows only. On-disk book files (Documents/Books,
    /// iCloud Documents/Books) are deliberately NOT removed — that storage is
    /// per-Apple-ID, not per-app-account, and touching it is a separate concern.
    ///
    /// Podcast deletion notes:
    /// - `PodcastSeries.episodes` is a `.cascade` relationship, so deleting a
    ///   series removes its owned episodes. We still fetch+delete ALL
    ///   `PodcastEpisode` explicitly to also clear series-less orphan episodes
    ///   (cascade does not reach them). Cascade-owned episodes are already gone
    ///   by then, so the all-episodes fetch only returns orphans — no double
    ///   delete.
    /// - `PodcastProgress` is an independent @Model (no relationship) and must
    ///   be deleted on its own.
    func clearUserData(reason: String) throws {
        AppLog.sync.info("Clearing all local user data (vocab + review + notebook + podcast + books)... reason=\(reason)")
        let entries = try modelContext.fetch(FetchDescriptor<VocabularyEntry>())
        for entry in entries {
            modelContext.delete(entry)
        }
        let reviews = try modelContext.fetch(FetchDescriptor<ReviewRecord>())
        for record in reviews {
            modelContext.delete(record)
        }
        let notebooks = try modelContext.fetch(FetchDescriptor<Notebook>())
        for notebook in notebooks {
            modelContext.delete(notebook)
        }
        // Delete series first; cascade removes their owned episodes.
        let series = try modelContext.fetch(FetchDescriptor<PodcastSeries>())
        for s in series {
            modelContext.delete(s)
        }
        // Remaining episodes are series-less orphans the cascade can't reach.
        let episodes = try modelContext.fetch(FetchDescriptor<PodcastEpisode>())
        for episode in episodes {
            modelContext.delete(episode)
        }
        let progress = try modelContext.fetch(FetchDescriptor<PodcastProgress>())
        for p in progress {
            modelContext.delete(p)
        }
        // `Book` is a user-scoped @Model (title/author/cover + reading position
        // & progression). It has no relationships, so a flat fetch+delete is
        // correct. Disk book files (Documents/Books, iCloud) are intentionally
        // left untouched — that is per-Apple-ID storage, out of scope here.
        let books = try modelContext.fetch(FetchDescriptor<Book>())
        for book in books {
            modelContext.delete(book)
        }
        try modelContext.save()
        AppLog.sync.info("Local data cleared. Deleted \(entries.count) vocab + \(reviews.count) review + \(notebooks.count) notebooks + \(series.count) podcast series + \(episodes.count) orphan episodes + \(progress.count) podcast progress + \(books.count) books. reason=\(reason)")
    }

    /// Returns the number of synced entries in the local store.
    func syncedEntryCount() throws -> Int {
        let descriptor = FetchDescriptor<VocabularyEntry>(
            predicate: #Predicate<VocabularyEntry> { $0.syncStatus == 1 }
        )
        return try modelContext.fetchCount(descriptor)
    }

    /// Deletes only server-synced entries (syncStatus == 1).
    /// Used on startup when not logged in to remove stale KG data
    /// while preserving locally-created pending words (syncStatus == 0).
    func clearSyncedData() throws {
        let descriptor = FetchDescriptor<VocabularyEntry>(
            predicate: #Predicate<VocabularyEntry> { $0.syncStatus == 1 }
        )
        let entries = try modelContext.fetch(descriptor)
        guard !entries.isEmpty else { return }
        entries.forEach { modelContext.delete($0) }
        try modelContext.save()
        AppLog.sync.info("Cleared \(entries.count) stale synced entries on startup.")
    }

    /// Build the payload for pushing review states to the backend.
    func buildReviewStatePushPayload() throws -> [[String: Any]] {
        let descriptor = FetchDescriptor<VocabularyEntry>(
            predicate: #Predicate<VocabularyEntry> { $0.syncStatus == 1 }
        )
        let entries = try modelContext.fetch(descriptor)

        var payload: [[String: Any]] = []
        for entry in entries {
            let lastReviewed = entry.lastReviewedAt ?? entry.dateAdded
            var item: [String: Any] = [
                "word": entry.word,
                "review_interval_hours": entry.reviewIntervalHours,
                "next_review_at": AppDateFormatters.iso8601.string(from: entry.nextReviewAt),
                "last_reviewed_at": AppDateFormatters.iso8601.string(from: lastReviewed),
                "review_count": entry.reviewCount,
                "lapse_count": entry.lapseCount,
                "review_streak": entry.reviewStreak,
                "last_review_feedback": entry.lastReviewFeedbackRaw,
            ]
            if let cardId = entry.kgCardId, !cardId.isEmpty {
                item["card_id"] = cardId
            }
            payload.append(item)
        }
        return payload
    }

    func distinctNotebookIds() throws -> [String] {
        let descriptor = FetchDescriptor<VocabularyEntry>()
        let entries = try modelContext.fetch(descriptor)
        return Array(Set(entries.map(\.notebookId)))
    }

    private static let dayFormatter = AppDateFormatters.dayKey

    // MARK: - Merge Key Helper

    private func mergeKey(_ word: String, notebookId: String) -> String {
        "\(word.precomposedStringWithCanonicalMapping.trimmingCharacters(in: .whitespaces).lowercased())|\(notebookId)"
    }

    // MARK: - Book Source Merge Helper

    /// Placeholder shown when a synced card carries no usable book source.
    static let fallbackBookTitle = "Knowledge Graph"

    /// Resolve the book title / chapter for a card from its server `source`
    /// metadata. iOS captures always originate from the reader so a card's
    /// `source.type` is `"book"`; non-book / missing / empty sources fall
    /// back to `fallbackBookTitle` with no chapter.
    ///
    /// This closes the sync-down gap from PR #533: the `source` field was
    /// decoded but never consumed, so synced cards permanently lost their
    /// book name and chapter.
    static func resolveSource(from card: KGCard) -> (bookTitle: String, chapterTitle: String?) {
        guard let source = card.source, source.type == "book" else {
            return (fallbackBookTitle, nil)
        }
        let title = source.title?.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let title, !title.isEmpty else {
            return (fallbackBookTitle, nil)
        }
        let chapter = source.chapter?.trimmingCharacters(in: .whitespacesAndNewlines)
        let resolvedChapter = (chapter?.isEmpty == false) ? chapter : nil
        return (title, resolvedChapter)
    }

    /// Backfill an existing entry's book title / chapter from server `source`.
    /// Only overwrites when the server actually supplies a usable book title —
    /// a missing/empty server source must not clobber a locally-known title.
    private static func applySource(from card: KGCard, into entry: VocabularyEntry) {
        guard let source = card.source, source.type == "book",
              let title = source.title?.trimmingCharacters(in: .whitespacesAndNewlines),
              !title.isEmpty else { return }
        entry.bookTitle = title
        let chapter = source.chapter?.trimmingCharacters(in: .whitespacesAndNewlines)
        entry.chapterTitle = (chapter?.isEmpty == false) ? chapter : nil
    }

    // MARK: - Review State Merge Helper

    /// Observability counter for the equal-instant (serverLast == localLast)
    /// branch where server-wins silently overwrites equally-fresh local
    /// feedback. Pure telemetry — does NOT change the >= merge decision.
    /// Merge runs single-threaded on the sync path; `nonisolated(unsafe)` is
    /// safe (statics are not actor-isolated, observation only).
    nonisolated(unsafe) static var reviewMergeEqualInstantConflicts = 0

    private static func mergeReviewState(from card: KGCard, into entry: VocabularyEntry) {
        guard let serverLastStr = card.lastReviewedAt,
              let serverLast = parseISO8601(serverLastStr) else { return }

        let localLast = entry.lastReviewedAt ?? .distantPast
        if serverLast >= localLast {
            if localLast != .distantPast {
                if serverLast == localLast {
                    reviewMergeEqualInstantConflicts += 1
                    AppLog.sync.info("Review merge conflict (equal-instant): server overwrites equally-fresh local feedback for '\(entry.word)' at \(serverLastStr); total=\(reviewMergeEqualInstantConflicts)")
                }
                AppLog.sync.info("Review merge: server wins for '\(entry.word)' (server=\(serverLastStr), local=\(AppDateFormatters.iso8601.string(from: localLast)))")
            }
            entry.reviewIntervalHours = card.reviewIntervalHours ?? entry.reviewIntervalHours
            if let nextStr = card.nextReviewAt, let nextDate = parseISO8601(nextStr) {
                entry.nextReviewAt = nextDate
            }
            entry.lastReviewedAt = serverLast
            entry.reviewCount = max(entry.reviewCount, card.reviewCount ?? 0)
            entry.lapseCount = max(entry.lapseCount, card.lapseCount ?? 0)
            entry.reviewStreak = max(entry.reviewStreak, card.reviewStreak ?? 0)
            entry.lastReviewFeedbackRaw = card.lastReviewFeedback ?? entry.lastReviewFeedbackRaw
        } else if localLast > serverLast {
            AppLog.sync.info("Review merge: local wins for '\(entry.word)' (local=\(AppDateFormatters.iso8601.string(from: localLast)), server=\(serverLastStr)), local review preserved")
        }
    }
}

extension BackgroundSyncActor {
    /// Build append-only review event payloads from local ReviewRecord rows.
    func buildReviewEventsPushPayload() throws -> [KGReviewEventPayload] {
        let descriptor = FetchDescriptor<ReviewRecord>()
        let records = try modelContext.fetch(descriptor)
        guard !records.isEmpty else { return [] }
        let entries = try modelContext.fetch(FetchDescriptor<VocabularyEntry>())
        let entriesByID = Dictionary(uniqueKeysWithValues: entries.map { ($0.id, $0) })

        return records.map { record in
            // 優先用複習當下固化在事件上的 kgCardId(自包含,不退化)。只有 legacy 紀錄
            // (固化前)才回退舊的 entryID→entry→kgCardId 三段反查 —— 卡若已離場仍會是
            // nil,但那是固化上線前的歷史殘留,新事件不再受此影響。
            let cardId: String?
            if let fixated = record.kgCardId, !fixated.isEmpty {
                cardId = fixated
            } else if let entryID = record.entryID,
                      let resolvedCardId = entriesByID[entryID]?.kgCardId,
                      !resolvedCardId.isEmpty {
                cardId = resolvedCardId
            } else {
                cardId = nil
            }
            return KGReviewEventPayload(
                event_id: record.id.uuidString,
                card_id: cardId,
                word_snapshot: record.word,
                notebook_id: record.notebookId,
                feedback: record.feedback,
                reviewed_at: AppDateFormatters.iso8601.string(from: record.reviewedAt),
                created_at: AppDateFormatters.iso8601.string(from: record.reviewedAt),
                interval_before: record.intervalBefore,
                interval_after: record.intervalAfter,
                next_review_before: record.nextReviewBefore.map { AppDateFormatters.iso8601.string(from: $0) },
                next_review_after: record.nextReviewAfter.map { AppDateFormatters.iso8601.string(from: $0) },
                review_count_after: record.reviewCountAfter,
                streak_after: record.streakAfter,
                lapse_after: record.lapseAfter
            )
        }
    }

    /// Merge remote append-only review events into local ReviewRecord rows.
    func mergeReviewEvents(_ remoteEvents: [KGReviewEventPayload]) throws {
        guard !remoteEvents.isEmpty else { return }

        let descriptor = FetchDescriptor<ReviewRecord>()
        let existing = try modelContext.fetch(descriptor)
        var existingIDs = Set(existing.map(\.id))
        let entries = try modelContext.fetch(FetchDescriptor<VocabularyEntry>())
        let entryIDsByCardID = Dictionary(
            uniqueKeysWithValues: entries.compactMap { entry -> (String, UUID)? in
                guard let cardID = entry.kgCardId, !cardID.isEmpty else { return nil }
                return (cardID, entry.id)
            }
        )
        var inserted = 0

        for event in remoteEvents {
            guard
                let eventID = UUID(uuidString: event.event_id),
                !existingIDs.contains(eventID),
                let reviewedAt = Self.parseISO8601(event.reviewed_at)
            else { continue }

            let record = ReviewRecord(
                word: event.word_snapshot,
                entryID: event.card_id.flatMap { entryIDsByCardID[$0] },
                feedback: event.feedback,
                reviewedAt: reviewedAt,
                // 固化遠端事件帶的 kgCardId + SRS 快照,本機即使查無對應 entry(卡未同步到)
                // 也保住 card 身分與學習曲線,下次上報不會因本機反查不到而退化。
                kgCardId: event.card_id.flatMap { $0.isEmpty ? nil : $0 },
                intervalBefore: event.interval_before,
                intervalAfter: event.interval_after,
                nextReviewBefore: event.next_review_before.flatMap { Self.parseISO8601($0) },
                nextReviewAfter: event.next_review_after.flatMap { Self.parseISO8601($0) },
                reviewCountAfter: event.review_count_after,
                streakAfter: event.streak_after,
                lapseAfter: event.lapse_after
            )
            record.id = eventID
            record.notebookId = event.notebook_id
            modelContext.insert(record)
            existingIDs.insert(eventID)
            inserted += 1
        }

        if inserted > 0 {
            try modelContext.save()
            AppLog.sync.info("mergeReviewEvents: inserted \(inserted) remote review events")
        }
    }
}
