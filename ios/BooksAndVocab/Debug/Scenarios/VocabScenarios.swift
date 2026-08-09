#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for the Vocabulary surface (OverviewTab, Knowledge Graph).
/// Preview harness visibility lifted from `private` → `internal` in:
/// - KnowledgeGraphPresenter.swift
enum VocabScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Overview Tab
        // NOTE: in-memory container is empty, so this renders the zero-data
        // state (no seeded entries) rather than a populated dashboard.
        playbook.addScenarios(of: "Vocabulary · Overview") {
            Scenario("Empty DB", layout: .fill) {
                AppThemeContainer {
                    OverviewTab()
                        .modelContainer(for: [VocabularyEntry.self, ReviewRecord.self, Notebook.self], inMemory: true)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: Knowledge Graph
        // The graph canvas is a WKWebView. Catalog runs in a real simulator
        // window so the system compositor renders it without a snapshot shim.
        playbook.addScenarios(of: "Vocabulary · Knowledge Graph") {
            Scenario("With Data", layout: .fill) {
                AppThemeContainer {
                    KnowledgeGraphPresenterPreviewHarness(
                        state: KnowledgeGraphPresenterPreviewData.state(showsSettings: false)
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Settings Open", layout: .fill) {
                AppThemeContainer {
                    KnowledgeGraphPresenterPreviewHarness(
                        state: KnowledgeGraphPresenterPreviewData.state(showsSettings: true)
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Empty", layout: .fill) {
                AppThemeContainer {
                    KnowledgeGraphPresenterPreviewHarness(
                        state: KnowledgeGraphPresenterPreviewData.emptyState
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("No Links", layout: .fill) {
                AppThemeContainer {
                    KnowledgeGraphPresenterPreviewHarness(
                        state: KnowledgeGraphPresenterPreviewData.noLinksState
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: Linked Card Overlay
        playbook.addScenarios(of: "Vocabulary · Linked Card") {
            Scenario("Single card", layout: .fill) {
                LinkedCardOverlayScene(fixture: .single)
            }
            Scenario("Stacked 3-deep", layout: .fill) {
                LinkedCardOverlayScene(fixture: .stacked)
            }
        }

        // MARK: Add Link Sheet
        playbook.addScenarios(of: "Vocabulary · Add Link") {
            Scenario("With candidates", layout: .fill) {
                AddLinkSheetScene(fixture: .withCandidates)
            }
            Scenario("No candidates", layout: .fill) {
                AddLinkSheetScene(fixture: .noCandidates)
            }
        }
    }
}

// MARK: - Fixtures

private enum VocabLinkedCardFixture {
    case single
    case stacked

    var entryIndices: [Int] {
        switch self {
        case .single:
            return [0]
        case .stacked:
            return [0, 1, 2]
        }
    }
}

private enum VocabAddLinkFixture {
    case withCandidates
    case noCandidates

    var sourceIndex: Int {
        0
    }

    var candidateIndices: [Int] {
        switch self {
        case .withCandidates:
            return [3, 4, 5]
        case .noCandidates:
            return []
        }
    }
}

// MARK: - Scene harnesses

private struct LinkedCardOverlayScene: View {
    let entries: [VocabularyEntry]
    @State private var stack: [VocabularyEntry]

    init(fixture: VocabLinkedCardFixture) {
        let entries = MainActor.assumeIsolated {
            Self.entries(at: fixture.entryIndices)
        }
        self.entries = entries
        self._stack = State(initialValue: entries)
    }

    var body: some View {
        AppThemeContainer {
            LinkedCardOverlayStack(stack: $stack, allEntries: entries)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    @MainActor
    private static func entries(at indices: [Int]) -> [VocabularyEntry] {
        VocabManifestEntries.entries(at: indices)
    }
}

private struct AddLinkSheetScene: View {
    let source: VocabularyEntry
    let candidates: [VocabularyEntry]

    init(fixture: VocabAddLinkFixture) {
        let payload = MainActor.assumeIsolated {
            Self.payload(for: fixture)
        }
        source = payload.source
        candidates = payload.candidates
    }

    var body: some View {
        AppThemeContainer {
            // AddLinkSheet reads `\.modelContext` for the dictionary
            // materialization path, so the scene must supply a container.
            AddLinkSheet(
                sourceEntry: source,
                allEntries: candidates + [source]
            )
            .modelContainer(
                for: [VocabularyEntry.self, ReviewRecord.self],
                inMemory: true
            )
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    @MainActor
    private static func payload(for fixture: VocabAddLinkFixture) -> (source: VocabularyEntry, candidates: [VocabularyEntry]) {
        let source = VocabManifestEntries.entry(at: fixture.sourceIndex)
        let candidates = VocabManifestEntries.entries(at: fixture.candidateIndices)
        return (source, candidates)
    }
}


private enum VocabManifestEntries {
    private static func seed() -> UIWorldVocabularySeed {
        FixtureDatasetStore.requireVocabularySeed(for: .vocabLinkedCards)
    }

    @MainActor
    static func entry(at index: Int) -> VocabularyEntry {
        entries(at: [index])[0]
    }

    @MainActor
    static func entries(at indices: [Int]) -> [VocabularyEntry] {
        let seed = seed()
        precondition(
            seed.entries.count == 6,
            "UI World vocabulary.vocabLinkedCards expected 6 entries, got \(seed.entries.count)"
        )
        for index in indices {
            precondition(
                seed.entries.indices.contains(index),
                "UI World vocabulary.vocabLinkedCards missing entry index \(index)"
            )
        }
        return indices.map {
            UITestFixtureSeed.makeVocabularyEntry(from: seed.entries[$0], notebookId: seed.notebookRemoteId)
        }
    }
}
#endif
