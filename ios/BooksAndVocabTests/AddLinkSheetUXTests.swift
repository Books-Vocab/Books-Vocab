import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

// MARK: - #2031 step copy

@Suite("Add Link step copy (#2031)", .serialized)
@MainActor
struct AddLinkStepCopyTests {
    /// Backend step id → the key whose copy says what that step actually does.
    private static let expectedKeys: [(id: String, key: String)] = [
        ("resolve_target", "addLink.step.resolveTarget"),
        ("translate", "addLink.step.translate"),
        ("create_card", "addLink.step.createCard"),
        ("enrich", "addLink.step.enrich"),
        ("create_link", "addLink.step.createLink"),
        ("local_projection", "addLink.step.localProjection"),
    ]

    @Test("a running creation labels each backend step with its own action copy")
    func runningCreationUsesStepCopy() async throws {
        let gate = Gate()
        let service = ScriptedCreationService(
            onStart: { _, _ in
                await gate.wait()
                return CreationFixtures.status("op-1", "running", sequence: 1)
            },
            onFetch: { _, _ in CreationFixtures.status("op-1", "running", sequence: 2) }
        )
        let container = try CreationFixtures.container()
        let coordinator = AddLinkCreationCoordinator(environment: CreationFixtures.environment())
        let source = CreationFixtures.entry("source", cardID: "src")
        coordinator.start(
            word: "luminous",
            sourceEntry: source,
            allEntries: [source],
            operationService: service,
            syncService: service,
            container: container
        )
        defer {
            coordinator.cancel()
            Task { await gate.release() }
        }

        #expect(coordinator.steps.map(\.id) == Self.expectedKeys.map(\.id))
        #expect(coordinator.steps.map(\.label) == Self.expectedKeys.map { L10n.string($0.key) })
        // The old labels described the wrong action ("no matching word",
        // "sync", a bare "create"); none may come back.
        let misleading = ["找不到符合的單字", "同步", "建立"].map(L10n.string)
        #expect(coordinator.steps.allSatisfy { !misleading.contains($0.label) })
    }

    @Test("every step label key is translated in all five locales")
    func stepKeysAreLocalized() {
        let languages: [AppLanguage] = [.english, .traditionalChinese, .simplifiedChinese, .japanese, .korean]
        for (_, key) in Self.expectedKeys {
            for language in languages {
                let value = L10n.string(key, language: language)
                #expect(value != key, "\(key) missing in \(language)")
                #expect(!value.isEmpty)
            }
        }
    }

    @Test("the step enum mirrors the backend id order")
    func stepEnumMatchesBackendOrder() {
        #expect(AddLinkStep.allCases.map(\.rawValue) == Self.expectedKeys.map(\.id))
        #expect(AddLinkStep.allCases.map(\.labelKey) == Self.expectedKeys.map(\.key))
    }
}

// MARK: - #2031 candidate snapshot

@Suite("Add Link search snapshot (#2031)")
@MainActor
struct AddLinkSearchSnapshotTests {
    private static func world() -> (source: VocabularyEntry, all: [VocabularyEntry]) {
        let source = CreationFixtures.entry("serendipity", cardID: "src")
        let fortuitous = CreationFixtures.entry("fortuitous", cardID: "c-fortuitous")
        let fortunate = CreationFixtures.entry("fortunate", cardID: "c-fortunate")
        let archived = CreationFixtures.entry("fortress", cardID: "c-fortress")
        archived.isArchived = true
        let pending = CreationFixtures.entry("pending", cardID: nil)
        let other = CreationFixtures.entry("fortune", cardID: "c-other", notebook: "other")
        return (source, [source, fortuitous, fortunate, archived, pending, other])
    }

    @Test(
        "candidates and target state match the per-reader computations they replace",
        arguments: ["", "   ", "fort", "FORT", "fortuitous", "fortress", "pending", "serendipity", "zzqxv"]
    )
    func snapshotMatchesLegacyComputation(query: String) {
        let (source, all) = Self.world()
        let snapshot = AddLinkSearchSnapshot.make(query: query, sourceEntry: source, allEntries: all)
        let legacy = AddLinkCoordinator.localCandidates(query: query, sourceEntry: source, allEntries: all)

        #expect(snapshot.candidates.map(\.id) == legacy.map(\.id))
        #expect(snapshot.trimmedQuery == query.trimmingCharacters(in: .whitespacesAndNewlines))
        if snapshot.isEmptyQuery {
            #expect(snapshot.exactTargetState == nil)
        } else {
            // Computed even beside partial matches: "create" stays reachable (#2030).
            #expect(
                snapshot.exactTargetState
                    == AddLinkCreationCoordinator.localTargetState(query: query, sourceEntry: source, allEntries: all)
            )
        }
    }

    @Test("row selection only accepts an entry that is a current candidate")
    func containsCandidate() {
        let (source, all) = Self.world()
        let snapshot = AddLinkSearchSnapshot.make(query: "fort", sourceEntry: source, allEntries: all)
        #expect(snapshot.containsCandidate(all[1]))
        #expect(!snapshot.containsCandidate(all[3]))
        #expect(!snapshot.containsCandidate(source))
    }
}
