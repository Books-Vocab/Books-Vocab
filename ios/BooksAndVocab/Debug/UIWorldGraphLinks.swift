//
//  UIWorldGraphLinks.swift
//  Books & Vocab
//
//  Shared catalog-scene builder: derives `KGGraphLink`s from UI World-
//  materialized entries' `graphLinksByKind`, so the manifest stays the single
//  link source for every graph-bearing scene (Knowledge Graph View, Stats View
//  關聯圖 thumbnail — per docs/reference/catalog_scope.md「Knowledge Graph View
//  契約」). Dataset-integrity violations fail fast instead of rendering a
//  silently wrong graph.
//

#if DEBUG
import Foundation

enum UIWorldGraphLinks {
    static func makeGraphLinks(
        from entries: [VocabularyEntry],
        fixtureID: UIWorldVocabularyFixtureID
    ) -> [KGGraphLink] {
        let cardIDs = Set(entries.compactMap(\.kgCardId))
        var links: [KGGraphLink] = []

        for entry in entries {
            guard let sourceID = entry.kgCardId else { continue }
            for summary in entry.graphLinksByKind.values.flatMap({ $0 }) where !summary.isHidden {
                guard cardIDs.contains(summary.cardId) else {
                    preconditionFailure(
                        "UI World vocabulary.\(fixtureID.rawValue) graph link \(summary.id) points to missing cardId \(summary.cardId)"
                    )
                }
                links.append(
                    KGGraphLink(
                        id: summary.id,
                        fromId: sourceID,
                        toId: summary.cardId,
                        kind: summary.kind,
                        confidence: summary.confidence,
                        reason: summary.reason
                    )
                )
            }
        }

        let uniqueIDs = Set(links.map(\.id))
        precondition(
            uniqueIDs.count == links.count,
            "UI World vocabulary.\(fixtureID.rawValue) graph links must have unique IDs"
        )
        return links
    }
}
#endif
