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
        // Data-bearing scenes are wrapped in CatalogGraphSnapshotScene: the
        // graph canvas lives in a WKWebView, invisible to `layer.render(in:)`
        // snapshots — the freezer settles the d3 layout and swaps in a
        // rasterized overlay first. Empty/No Links render the native empty
        // state (no webview), so they need no wrapper.
        playbook.addScenarios(of: "Vocabulary · Knowledge Graph") {
            Scenario("With Data", layout: .fill) { context in
                CatalogGraphSnapshotScene(context: context) {
                    AppThemeContainer {
                        KnowledgeGraphPresenterPreviewHarness(
                            state: KnowledgeGraphPresenterPreviewData.state(showsSettings: false)
                        )
                    }
                    .environmentObject(AppAppearanceStore.preview)
                }
            }
            Scenario("Settings Open", layout: .fill) { context in
                CatalogGraphSnapshotScene(context: context) {
                    AppThemeContainer {
                        KnowledgeGraphPresenterPreviewHarness(
                            state: KnowledgeGraphPresenterPreviewData.state(showsSettings: true)
                        )
                    }
                    .environmentObject(AppAppearanceStore.preview)
                }
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
            Scenario("Dictionary loading", layout: .fill) {
                AddLinkSheetScene(fixture: .dictionaryLoading)
            }
            Scenario("Dictionary result", layout: .fill) {
                AddLinkSheetScene(fixture: .dictionaryResult)
            }
            Scenario("Dictionary empty", layout: .fill) {
                AddLinkSheetScene(fixture: .dictionaryEmpty)
            }
            Scenario("Dictionary error", layout: .fill) {
                AddLinkSheetScene(fixture: .dictionaryError)
            }
            Scenario("Dictionary stale", layout: .fill) {
                AddLinkSheetScene(fixture: .dictionaryStale)
            }
            Scenario("Long content", layout: .fill) {
                AddLinkSheetScene(fixture: .longContent)
            }
            Scenario("Narrow width", layout: .fill) {
                AddLinkSheetScene(fixture: .dictionaryResult)
                    .frame(width: 320)
            }
            Scenario("Accessibility 3", layout: .fill) {
                AddLinkSheetScene(fixture: .dictionaryResult)
                    .dynamicTypeSize(.accessibility3)
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
    case dictionaryLoading
    case dictionaryResult
    case dictionaryEmpty
    case dictionaryError
    case dictionaryStale
    case longContent

    var sourceIndex: Int {
        0
    }

    var candidateIndices: [Int] {
        switch self {
        case .withCandidates:
            return [3, 4, 5]
        case .noCandidates, .dictionaryLoading, .dictionaryResult,
             .dictionaryEmpty, .dictionaryError, .dictionaryStale, .longContent:
            return []
        }
    }

    var query: String {
        switch self {
        case .withCandidates, .noCandidates: return ""
        case .longContent: return "antidisestablishmentarianism"
        default: return "lucid"
        }
    }

    var searchPhase: DictionarySearchPhase {
        switch self {
        case .withCandidates, .noCandidates: return .idle
        case .dictionaryLoading: return .loading
        case .dictionaryResult:
            return .result(VocabDictionaryEntryFixture.standard, cacheStatus: "fresh")
        case .dictionaryEmpty: return .empty
        case .dictionaryError: return .failed(.rateLimited)
        case .dictionaryStale:
            return .result(VocabDictionaryEntryFixture.standard, cacheStatus: "stale")
        case .longContent:
            return .result(VocabDictionaryEntryFixture.longContent, cacheStatus: "fresh")
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
    private let fixture: VocabAddLinkFixture

    init(fixture: VocabAddLinkFixture) {
        let payload = MainActor.assumeIsolated {
            Self.payload(for: fixture)
        }
        self.fixture = fixture
        source = payload.source
        candidates = payload.candidates
    }

    var body: some View {
        AppThemeContainer {
            AddLinkSheet(
                sourceEntry: source,
                allEntries: candidates + [source],
                initialQuery: fixture.query,
                initialSearchPhase: fixture.searchPhase
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

private enum VocabDictionaryEntryFixture {
    static let standard = decode(Self.standardJSON)
    static let longContent = decode(Self.longContentJSON)

    private static func decode(_ json: String) -> LexicalEntry {
        do {
            return try JSONDecoder().decode(LexicalEntry.self, from: Data(json.utf8))
        } catch {
            preconditionFailure("Invalid Add Link catalog lexical fixture: \(error)")
        }
    }

    private static let standardJSON = #"""
    {
      "provider":"free_dictionary","dictionary_id":"wiktionary-en","schema_version":"1",
      "entry_key":"en.bHVjaWQ","word":"lucid","language":"en","pronunciations":["/ˈluːsɪd/"],"forms":[],
      "senses":[{"key":"sense_1","part_of_speech":"adjective","definition":"Expressed clearly and easy to understand.",
      "examples":[{"key":"example_1","text":"The explanation was lucid and persuasive."}],"translations":[],"synonyms":[],"antonyms":[]}],
      "attribution":{"provider":"free_dictionary","source_url":"https://en.wiktionary.org/wiki/lucid","license_name":"CC BY-SA 4.0","license_url":"https://creativecommons.org/licenses/by-sa/4.0/","attribution_text":"Wiktionary contributors"},
      "fetched_at":"2026-08-05T00:00:00Z","truncated":false
    }
    """#

    private static let longContentJSON = #"""
    {
      "provider":"free_dictionary","dictionary_id":"wiktionary-en","schema_version":"1",
      "entry_key":"en.long","word":"antidisestablishmentarianism","language":"en","pronunciations":["/ˌæn.ti.dɪs.ɪˌstæb.lɪʃ.mənˈteə.ri.ə.nɪ.zəm/"],"forms":[],
      "senses":[{"key":"sense_long","part_of_speech":"a deliberately long catalog-only part-of-speech label","definition":"A deliberately extended definition used to verify that exceptionally long provider content truncates without displacing controls or breaking the rhythm of the result list.",
      "examples":[{"key":"example_long","text":"This intentionally oversized example sentence verifies multi-line truncation when dictionary content is substantially longer than ordinary reading material and the available row width is constrained."}],"translations":[],"synonyms":[],"antonyms":[]}],
      "attribution":{"provider":"free_dictionary","source_url":"https://en.wiktionary.org/wiki/antidisestablishmentarianism","license_name":"Creative Commons Attribution-ShareAlike 4.0 International","license_url":"https://creativecommons.org/licenses/by-sa/4.0/","attribution_text":"A deliberately long attribution supplied by Wiktionary contributors for catalog stress verification"},
      "fetched_at":"2026-08-05T00:00:00Z","truncated":false
    }
    """#
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
