import Foundation

struct VocabularyGraphLinkMutation {
    struct PendingManualLink: Equatable {
        let placeholderId: String
        let placeholderKind: String
        let targetCardId: String
        let targetWord: String
    }

    struct LinkRemovalSnapshot {
        let source: (kind: String, link: KGCardLinkSummary)?
        let peer: (kind: String, link: KGCardLinkSummary)?
    }

    static func beginManualLink(
        from source: VocabularyEntry,
        to target: VocabularyEntry
    ) -> PendingManualLink? {
        guard source.kgCardId != nil, let targetCardId = target.kgCardId else { return nil }

        let allLinks = source.graphLinksByKind.values.flatMap { $0 }
        guard !allLinks.contains(where: { $0.cardId == targetCardId }) else { return nil }

        let placeholderId = "pending-\(UUID().uuidString)"
        let placeholder = KGCardLinkSummary.pending(
            id: placeholderId,
            cardId: targetCardId,
            word: target.word
        )
        source.insertLink(placeholder, kind: placeholder.kind)
        return PendingManualLink(
            placeholderId: placeholderId,
            placeholderKind: placeholder.kind,
            targetCardId: targetCardId,
            targetWord: target.word
        )
    }

    static func commitManualLink(
        _ pending: PendingManualLink,
        result: KGGraphLink,
        on source: VocabularyEntry
    ) {
        removePlaceholder(pending, from: source)
        let summary = KGCardLinkSummary(
            id: result.id,
            cardId: pending.targetCardId,
            word: pending.targetWord,
            kind: result.kind,
            label: result.kind == "contrasts_with" ? "對比" : "相關",
            confidence: result.confidence,
            reason: result.reason,
            hidden: false
        )
        source.insertLink(summary, kind: result.kind)
    }

    static func rollbackManualLink(
        _ pending: PendingManualLink,
        on source: VocabularyEntry
    ) {
        removePlaceholder(pending, from: source)
    }

    static func removeLink(
        _ link: KGCardLinkSummary,
        from source: VocabularyEntry,
        peer: VocabularyEntry? = nil
    ) -> LinkRemovalSnapshot {
        LinkRemovalSnapshot(
            source: source.mutateLink(id: link.id) { _ in nil },
            peer: peer?.mutateLink(id: link.id) { _ in nil }
        )
    }

    static func rollbackLinkRemoval(
        _ snapshot: LinkRemovalSnapshot,
        source: VocabularyEntry,
        peer: VocabularyEntry? = nil
    ) {
        if let sourceSnapshot = snapshot.source {
            source.insertLink(sourceSnapshot.link, kind: sourceSnapshot.kind)
        }
        if let peerSnapshot = snapshot.peer {
            peer?.insertLink(peerSnapshot.link, kind: peerSnapshot.kind)
        }
    }

    static func setHidden(
        _ hidden: Bool,
        for link: KGCardLinkSummary,
        source: VocabularyEntry,
        peer: VocabularyEntry? = nil
    ) {
        source.mutateLink(id: link.id) { $0.withHidden(hidden) }
        peer?.mutateLink(id: link.id) { $0.withHidden(hidden) }
    }

    private static func removePlaceholder(
        _ pending: PendingManualLink,
        from source: VocabularyEntry
    ) {
        source.mutateLink(id: pending.placeholderId) { _ in nil }
    }
}
