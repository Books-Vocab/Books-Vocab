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
                        // presentsEagerly: the catalog snapshot renders synchronously
                        // and does not await WordDetailSheet's deferred presentation
                        // `.task`, so seed the card up front (otherwise the shot
                        // captures the "載入中" loading placeholder). Data still pins
                        // the `.wordDetail` QA seed (ephemeral entry).
                        WordDetailSheet(entry: Self.entry(.rich), allEntries: Self.entries(), presentsEagerly: true)
                    }
                    .environmentObject(AppAppearanceStore.preview)
                }
            }
            Scenario("Minimal entry", layout: .fill) {
                MainActor.assumeIsolated {
                    AppThemeContainer {
                        // presentsEagerly: same catalog-snapshot seam as "Rich entry".
                        // Data still pins the `.wordDetail` QA seed (terse entry).
                        WordDetailSheet(entry: Self.entry(.minimal), allEntries: Self.entries(), presentsEagerly: true)
                    }
                    .environmentObject(AppAppearanceStore.preview)
                }
            }
            // Marketing capture source for `ops/capture_profiles/website.json`
            // (review_card shot). Renders the full Word Detail card — definition,
            // pronunciation, example, related words — content-vertically pinned to
            // the top (unlike Today Review's fold, whose front card overlaps the
            // answer). Driven by `marketingCapture.wordDetail`: entries[0] is the
            // focused hero, the whole seed is `allEntries` so its graph links
            // resolve to real related cards.
            Scenario("Marketing", layout: .fill) {
                MainActor.assumeIsolated {
                    Self.marketingSheet()
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

    /// Materializes the marketing Word Detail seed (`marketingCapture.wordDetail`)
    /// into `VocabularyEntry` models. `entries[0]` is the focused hero card; the
    /// rest are its graph-link targets, so `WordDetailSheet(allEntries:)` resolves
    /// the related-word links to real cards. Distinct from the `.wordDetail` QA
    /// seed (ephemeral/terse), which the QA scenarios keep pinning.
    @MainActor
    private static func marketingEntries() -> [VocabularyEntry] {
        guard let seed = FixtureDatasetStore.marketingCapture()?.wordDetail else {
            preconditionFailure("marketingCapture.wordDetail is required for the Word Detail marketing catalog scene")
        }
        precondition(
            !seed.entries.isEmpty,
            "marketingCapture.wordDetail must declare at least one entry (the focused hero card)"
        )
        return seed.entries.map {
            UITestFixtureSeed.makeVocabularyEntry(from: $0, notebookId: seed.notebookRemoteId)
        }
    }

    /// Hoisted so the `Scenario` closure stays a single expression (multi-statement
    /// closures inside `MainActor.assumeIsolated` break `Scenario` init overload
    /// resolution). `entries[0]` is the hero; the whole seed is `allEntries`.
    @MainActor
    private static func marketingSheet() -> some View {
        let entries = marketingEntries()
        return AppThemeContainer {
            // presentsEagerly: the catalog snapshot captures synchronously and
            // does not await WordDetailSheet's deferred presentation `.task`, so
            // seed the card presentation up front (otherwise the shot captures the
            // "載入中" loading placeholder).
            WordDetailSheet(entry: entries[0], allEntries: entries, presentsEagerly: true)
        }
        // Force light: website.json marks the review_card shot `appearance: light`;
        // keeps the card a clean white surface, consistent with the reader/vocab
        // marketing shots (AppThemeContainer(.system) would otherwise follow the
        // dark sim).
        .environment(\.colorScheme, .light)
        .environmentObject(AppAppearanceStore.preview)
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
