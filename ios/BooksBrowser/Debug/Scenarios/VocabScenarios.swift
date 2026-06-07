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
                LinkedCardOverlayScene(entries: [Self.sampleEntry(word: "serendipity")])
            }
            Scenario("Stacked 3-deep", layout: .fill) {
                LinkedCardOverlayScene(entries: [
                    Self.sampleEntry(word: "serendipity"),
                    Self.sampleEntry(word: "epiphany"),
                    Self.sampleEntry(word: "revelation"),
                ])
            }
        }

        // MARK: Add Link Sheet
        playbook.addScenarios(of: "Vocabulary · Add Link") {
            Scenario("With candidates", layout: .fill) {
                AddLinkSheetScene(
                    source: Self.sampleEntry(word: "serendipity"),
                    candidates: [
                        Self.sampleEntry(word: "fortuitous"),
                        Self.sampleEntry(word: "fortunate"),
                        Self.sampleEntry(word: "happy accident"),
                    ]
                )
            }
            Scenario("No candidates", layout: .fill) {
                AddLinkSheetScene(
                    source: Self.sampleEntry(word: "serendipity"),
                    candidates: []
                )
            }
        }
    }

    // MARK: - Fixtures

    private static func sampleEntry(word: String) -> VocabularyEntry {
        VocabularyEntry(
            word: word,
            translation: "機緣巧合",
            context: "It was pure \(word) that we met.",
            explanation: "A happy accident; finding something good without looking for it.",
            partOfSpeech: "n.",
            bookTitle: "Sample Book"
        )
    }
}

// MARK: - Scene harnesses

private struct LinkedCardOverlayScene: View {
    let entries: [VocabularyEntry]
    @State private var stack: [VocabularyEntry]

    init(entries: [VocabularyEntry]) {
        self.entries = entries
        self._stack = State(initialValue: entries)
    }

    var body: some View {
        AppThemeContainer {
            LinkedCardOverlayStack(stack: $stack, allEntries: entries)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

private struct AddLinkSheetScene: View {
    let source: VocabularyEntry
    let candidates: [VocabularyEntry]

    var body: some View {
        AppThemeContainer {
            AddLinkSheet(
                sourceEntry: source,
                allEntries: candidates + [source],
                onSelect: { _ in }
            )
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
