#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for Word Detail surface — WordDetailSheet (full presenter,
/// data-driven from UI World VocabularyEntry seeds) and CardDocumentView (the
/// reusable card body, rendered from the same seeded card presentation).
///
/// 不掛 backend / SwiftData container：WordDetailSheet 在 `.task` 內由
/// `entry.cardPresentation` 同步計算 presenter state；entry content 仍由
/// UI World manifest 擔任 SoT。
enum WordDetailScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Word Detail Sheet
        playbook.addScenarios(of: "Word Detail · Sheet") {
            Scenario("Rich entry", layout: .fill) {
                MainActor.assumeIsolated {
                    AppThemeContainer {
                        WordDetailSheet(entry: Self.entry(.rich), allEntries: Self.entries())
                    }
                    .environmentObject(AppAppearanceStore.preview)
                }
            }
            Scenario("Minimal entry", layout: .fill) {
                MainActor.assumeIsolated {
                    AppThemeContainer {
                        WordDetailSheet(entry: Self.entry(.minimal), allEntries: Self.entries())
                    }
                    .environmentObject(AppAppearanceStore.preview)
                }
            }
        }

        // MARK: Card Document
        playbook.addScenarios(of: "Word Detail · Card Document") {
            Scenario("Full", layout: .compressed) {
                MainActor.assumeIsolated {
                    cardSheet(document: Self.document(.rich), compact: false)
                }
            }
            Scenario("Compact", layout: .compressed) {
                MainActor.assumeIsolated {
                    cardSheet(document: Self.document(.rich), compact: true)
                }
            }
            Scenario("No example / collocations", layout: .compressed) {
                MainActor.assumeIsolated {
                    cardSheet(document: Self.document(.minimal), compact: false)
                }
            }
        }
    }

    // MARK: - Card sheet helper

    private static func cardSheet(document: CardDocument, compact: Bool) -> some View {
        let skin = AppSkin.previewNeutral
        return ScrollView {
            CardDocumentView(document: document, compact: compact)
                .padding(skin.metrics.cardBlockPadding)
        }
        .background(skin.palette.pageBackground.ignoresSafeArea())
        .appSkin(skin)
    }

    // MARK: - Fixtures

    private enum WordDetailFixture {
        case rich
        case minimal

        var word: String {
            switch self {
            case .rich:
                return "ephemeral"
            case .minimal:
                return "terse"
            }
        }
    }

    private static func seed() -> UIWorldVocabularySeed {
        FixtureDatasetStore.requireVocabularySeed(for: .wordDetail)
    }

    @MainActor
    private static func entries() -> [VocabularyEntry] {
        let seed = seed()
        return seed.entries.map {
            UITestFixtureSeed.makeVocabularyEntry(from: $0, notebookId: seed.notebookRemoteId)
        }
    }

    @MainActor
    private static func entry(_ fixture: WordDetailFixture) -> VocabularyEntry {
        let matches = entries().filter { $0.word == fixture.word }
        precondition(
            matches.count == 1,
            "UI World vocabulary.wordDetail expected exactly one entry for \(fixture.word), got \(matches.count)"
        )
        return matches[0]
    }

    @MainActor
    private static func document(_ fixture: WordDetailFixture) -> CardDocument {
        entry(fixture).cardPresentation.document
    }
}
#endif
