import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

/// A1 (frozen source) and A3 (stale lookup) are both "the review session holds
/// a start-of-session snapshot while the store keeps changing".
@Suite("Review link entry resolver", .serialized)
@MainActor
struct ReviewLinkEntryResolverTests {
    private func insert(_ entries: VocabularyEntry..., into container: ModelContainer) throws {
        for entry in entries { container.mainContext.insert(entry) }
        try container.mainContext.save()
    }

    private func snapshot(of entries: [VocabularyEntry]) -> [String: VocabularyEntry] {
        entries.reduce(into: [:]) { lookup, entry in
            if let id = entry.kgCardId { lookup[id] = entry }
        }
    }

    @Test("A3: a card created after the session snapshot is still found for navigation")
    func findsCardCreatedAfterSnapshot() throws {
        let container = try CreationFixtures.container()
        let existing = CreationFixtures.entry("existing", cardID: "card-a")
        try insert(existing, into: container)
        let frozen = snapshot(of: [existing])

        // A pull (or the Add Link creation) lands a new card mid-session.
        let created = CreationFixtures.entry("luminous", cardID: "card-new")
        try insert(created, into: container)

        #expect(frozen["card-new"] == nil, "precondition: the snapshot cannot know the new card")
        let resolved = ReviewLinkEntryResolver.entry(
            forCardID: "card-new", snapshot: frozen, context: container.mainContext
        )
        #expect(resolved === created)
    }

    @Test("the snapshot stays the fast path for cards it already knows")
    func snapshotWins() throws {
        let container = try CreationFixtures.container()
        let known = CreationFixtures.entry("known", cardID: "card-a")
        try insert(known, into: container)

        let resolved = ReviewLinkEntryResolver.entry(
            forCardID: "card-a", snapshot: snapshot(of: [known]), context: container.mainContext
        )
        #expect(resolved === known)
    }

    @Test("an unknown or empty card id resolves to nil so the caller can tell the user")
    func unknownCardIsNil() throws {
        let container = try CreationFixtures.container()
        #expect(ReviewLinkEntryResolver.entry(forCardID: "nope", snapshot: [:], context: container.mainContext) == nil)
        #expect(ReviewLinkEntryResolver.entry(forCardID: "", snapshot: [:], context: container.mainContext) == nil)
    }

    @Test("A3: searching the same word again sees the card the first attempt created")
    func addLinkCandidatesAreLive() throws {
        let container = try CreationFixtures.container()
        let source = CreationFixtures.entry("source", cardID: "card-src")
        try insert(source, into: container)
        let sessionEntries = [source]

        #expect(AddLinkCreationCoordinator.localTargetState(
            query: "luminous", sourceEntry: source, allEntries: sessionEntries
        ) == .missing)

        let created = CreationFixtures.entry("luminous", cardID: "card-new")
        try insert(created, into: container)

        let request = ReviewLinkEntryResolver.addLinkRequest(
            sourceEntry: source, sessionEntries: sessionEntries, context: container.mainContext
        )
        #expect(request.allEntries.contains { $0 === created })
        #expect(AddLinkCreationCoordinator.localTargetState(
            query: "luminous", sourceEntry: source, allEntries: request.allEntries
        ) == .active)
        #expect(AddLinkCoordinator.localCandidates(
            query: "lumin", sourceEntry: source, allEntries: request.allEntries
        ).map(\.word) == ["luminous"])
    }

    @Test("A1: the sheet request is frozen to the card it was opened on")
    func requestFreezesSourceEntry() throws {
        let container = try CreationFixtures.container()
        let opened = CreationFixtures.entry("opened-on", cardID: "card-1")
        let next = CreationFixtures.entry("autoplay-advanced-to", cardID: "card-2")
        try insert(opened, into: container)
        try insert(next, into: container)

        var currentEntry = opened
        let request = ReviewLinkEntryResolver.addLinkRequest(
            sourceEntry: currentEntry, sessionEntries: [opened, next], context: container.mainContext
        )
        currentEntry = next // autoplay moves the live "current card" under the sheet

        #expect(request.sourceEntry === opened)
        #expect(request.sourceEntry !== currentEntry)
    }

    @Test("live candidate pool is the whole store, not the session snapshot")
    func liveEntriesComeFromTheStore() throws {
        let container = try CreationFixtures.container()
        let a = CreationFixtures.entry("a", cardID: "1")
        let b = CreationFixtures.entry("b", cardID: "2")
        try insert(a, b, into: container)

        let live = ReviewLinkEntryResolver.liveEntries(in: container.mainContext, fallback: [a])
        #expect(Set(live.map(\.word)) == ["a", "b"])
    }
}
