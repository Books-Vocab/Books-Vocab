import Foundation
import SwiftUI
import Testing
@testable import BooksAndVocab

/// #2038: what Return does in the Add Link search field, as a pure function of
/// the input state. The invariant under test: Return never creates and never
/// picks among partial matches.
@Suite("Add Link Return key (#2038)")
@MainActor
struct AddLinkReturnKeyTests {
    private func behavior(
        _ query: String,
        source: VocabularyEntry,
        entries: [VocabularyEntry]
    ) -> AddLinkReturnBehavior {
        let snapshot = AddLinkSearchSnapshot.make(
            query: query,
            sourceEntry: source,
            allEntries: [source] + entries
        )
        return AddLinkReturnBehavior.resolve(snapshot)
    }

    private func source() -> VocabularyEntry {
        CreationFixtures.entry("serendipity", cardID: "src")
    }

    @Test("an exactly typed linkable word is linked, and the key says so")
    func exactMatchLinks() {
        let source = source()
        let run = CreationFixtures.entry("run", cardID: "c-run")
        let running = CreationFixtures.entry("running", cardID: "c-running")

        let result = behavior("run", source: source, entries: [run, running])
        #expect(result == .linkExact(run.id), "the exact word wins over the partial match `running`")
        #expect(result.linksOnReturn)
        #expect(result.submitLabel == .join)
        #expect(result.accessibilityValue == "linkExact")
    }

    @Test("an exact word beyond the candidate cap is listed first and still linkable on Return")
    func exactMatchBeyondCandidateCapIsFirstAndLinkable() {
        let source = source()
        // 25 partial matches precede the exact word in store order.
        let partials = (0..<25).map { CreationFixtures.entry("set\($0)", cardID: "c-partial-\($0)") }
        let exact = CreationFixtures.entry("set", cardID: "c-set")

        let snapshot = AddLinkSearchSnapshot.make(
            query: "set",
            sourceEntry: source,
            allEntries: [source] + partials + [exact]
        )
        #expect(snapshot.candidates.first?.id == exact.id, "exact match sorts first")
        #expect(snapshot.candidates.count == AddLinkCoordinator.candidateLimit, "the cap still bounds the list")
        #expect(AddLinkReturnBehavior.resolve(snapshot) == .linkExact(exact.id))
        #expect(
            snapshot.candidates.dropFirst().map(\.word) == (0..<19).map { "set\($0)" },
            "partial matches keep store order behind the exact word"
        )
    }

    @Test("exactness uses the backend's normalization: case, whitespace, trailing punctuation")
    func exactMatchIsNormalized() {
        let source = source()
        let run = CreationFixtures.entry("run", cardID: "c-run")
        for typed in ["RUN", "  run  ", "run.", "Run?!", "run,"] {
            #expect(behavior(typed, source: source, entries: [run]) == .linkExact(run.id), "\(typed)")
        }
    }

    @Test("a lone partial match is NOT linked: Return only puts the keyboard away")
    func singlePartialMatchDoesNotAutoLink() {
        let source = source()
        let running = CreationFixtures.entry("running", cardID: "c-running")

        let result = behavior("runn", source: source, entries: [running])
        #expect(result == .dismissKeyboard)
        #expect(!result.linksOnReturn)
        #expect(result.submitLabel == .done)
    }

    @Test("several partial matches: keyboard away so the whole list is visible")
    func manyPartialMatchesDismissKeyboard() {
        let source = source()
        let entries = [
            CreationFixtures.entry("running", cardID: "c-1"),
            CreationFixtures.entry("runner", cardID: "c-2"),
        ]
        #expect(behavior("run", source: source, entries: entries) == .dismissKeyboard)
    }

    @Test("a word nothing has reveals the create entry and never creates")
    func unknownWordRevealsCreate() {
        let source = source()
        let entries = [CreationFixtures.entry("running", cardID: "c-running")]

        let result = behavior("zzqxv", source: source, entries: entries)
        #expect(result == .revealCreate)
        #expect(!result.linksOnReturn)
        #expect(result.submitLabel == .done)
    }

    @Test("the create entry is only revealed when there is nothing else to show")
    func partialMatchesNeverRevealCreate() {
        // `run` is not in the notebook but `running` is: the create entry is
        // offered next to it, yet Return still only dismisses the keyboard.
        let source = source()
        let result = behavior(
            "run",
            source: source,
            entries: [CreationFixtures.entry("running", cardID: "c-running")]
        )
        #expect(result == .dismissKeyboard)
        #expect(result != .revealCreate)
    }

    @Test("an exact word the source already links to does nothing but say so")
    func alreadyLinkedWord() {
        let source = source()
        let banana = CreationFixtures.entry("banana", cardID: "c-banana")
        source.graphLinksByKind = [
            "shares_usage": [
                KGCardLinkSummary(
                    id: "l1", cardId: "c-banana", word: "banana", kind: "shares_usage",
                    label: "x", confidence: 1, reason: "r"
                )
            ]
        ]

        let result = behavior("banana", source: source, entries: [banana])
        #expect(result == .alreadyLinked)
        #expect(!result.linksOnReturn)
        #expect(result.submitLabel == .done)
    }

    @Test("words that cannot be linked never link on Return")
    func nonLinkableStatesDismissKeyboard() {
        let source = source()
        let archived = CreationFixtures.entry("fortress", cardID: "c-fortress")
        archived.isArchived = true
        let pending = CreationFixtures.entry("pending", cardID: nil)

        #expect(behavior("fortress", source: source, entries: [archived]) == .dismissKeyboard)
        #expect(behavior("pending", source: source, entries: [pending]) == .dismissKeyboard)
        #expect(behavior("serendipity", source: source, entries: []) == .dismissKeyboard, "the source word itself")
    }

    @Test("an empty query only dismisses the keyboard")
    func emptyQuery() {
        let source = source()
        let entries = [CreationFixtures.entry("run", cardID: "c-run")]
        #expect(behavior("", source: source, entries: entries) == .dismissKeyboard)
        #expect(behavior("   ", source: source, entries: entries) == .dismissKeyboard)
    }

    @Test("no input state ever maps to a creating behavior")
    func noStateCreates() {
        // The enum has no case that starts a creation: exhaustively, every
        // behavior is link / acknowledge / keyboard / highlight.
        let all: [AddLinkReturnBehavior] = [
            .linkExact(UUID()), .alreadyLinked, .dismissKeyboard, .revealCreate,
        ]
        for value in all {
            switch value {
            case .linkExact, .alreadyLinked, .dismissKeyboard, .revealCreate: break
            }
        }
        #expect(all.filter(\.linksOnReturn).count == 1)
    }

    @Test("the already-linked toast copy is localized everywhere and names the word")
    func alreadyLinkedCopy() {
        let languages: [AppLanguage] = [.english, .traditionalChinese, .simplifiedChinese, .japanese, .korean]
        for language in languages {
            let text = L10n.format("addLink.return.alreadyLinked", language: language, "banana")
            #expect(text.contains("banana"), "\(language)")
            #expect(!text.hasPrefix("addLink."), "\(language) must be localized")
        }
    }
}
