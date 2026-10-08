import Foundation
import SwiftData

/// What the Add Link sheet is opened *for*, frozen at the moment the user taps
/// "+". The source card and candidate list never follow the review queue
/// afterwards, so a sheet that outlives several autoplay ticks still links the
/// card it was opened on.
struct AddLinkSheetRequest: Identifiable {
    let id = UUID()
    let sourceEntry: VocabularyEntry
    let allEntries: [VocabularyEntry]
}

/// Identity of a pending-creation item whose detail the user opened.
struct PendingLinkDetailRequest: Identifiable {
    let link: KGCardLinkSummary
    var id: String { link.id }
}

/// Resolves link targets against the live store.
///
/// `TodayReviewState.linkedEntryLookup` and the review session's `allEntries`
/// are snapshots taken when the session starts. A card created mid-session
/// (Add Link creation, a sync pull) is in SwiftData but not in either, so the
/// snapshot is only the fast path and the store is the source of truth.
enum ReviewLinkEntryResolver {
    @MainActor
    static func entry(
        forCardID cardID: String,
        snapshot: [String: VocabularyEntry],
        context: ModelContext
    ) -> VocabularyEntry? {
        guard !cardID.isEmpty else { return nil }
        if let hit = snapshot[cardID] { return hit }
        let target: String? = cardID
        var descriptor = FetchDescriptor<VocabularyEntry>(
            predicate: #Predicate { $0.kgCardId == target }
        )
        descriptor.fetchLimit = 1
        return try? context.fetch(descriptor).first
    }

    /// Fresh candidate pool for the Add Link sheet; falls back to the session
    /// snapshot only when the store cannot be read.
    @MainActor
    static func liveEntries(in context: ModelContext, fallback: [VocabularyEntry]) -> [VocabularyEntry] {
        (try? context.fetch(FetchDescriptor<VocabularyEntry>())) ?? fallback
    }

    @MainActor
    static func addLinkRequest(
        sourceEntry: VocabularyEntry,
        sessionEntries: [VocabularyEntry],
        context: ModelContext
    ) -> AddLinkSheetRequest {
        AddLinkSheetRequest(
            sourceEntry: sourceEntry,
            allEntries: liveEntries(in: context, fallback: sessionEntries)
        )
    }
}
