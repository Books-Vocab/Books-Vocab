#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for Word Detail surface — WordDetailSheet (full presenter,
/// data-driven from a synthetic VocabularyEntry) and CardDocumentView (the
/// reusable card body, rendered from a CardDocumentBuilder document).
///
/// 不掛 backend / SwiftData container：WordDetailSheet 在 `.task` 內由
/// `entry.cardPresentation` 同步計算 presenter state，故餵一個 in-memory
/// VocabularyEntry 即可完整渲染。
enum WordDetailScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Word Detail Sheet
        playbook.addScenarios(of: "Word Detail · Sheet") {
            Scenario("Rich entry", layout: .fill) {
                AppThemeContainer {
                    WordDetailSheet(entry: Self.richEntry(), allEntries: [])
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Minimal entry", layout: .fill) {
                AppThemeContainer {
                    WordDetailSheet(entry: Self.minimalEntry(), allEntries: [])
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: Card Document
        playbook.addScenarios(of: "Word Detail · Card Document") {
            Scenario("Full", layout: .compressed) {
                cardSheet(document: Self.richDocument(), compact: false)
            }
            Scenario("Compact", layout: .compressed) {
                cardSheet(document: Self.richDocument(), compact: true)
            }
            Scenario("No example / collocations", layout: .compressed) {
                cardSheet(document: Self.minimalDocument(), compact: false)
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

    private static func richEntry() -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: "ephemeral",
            translation: "短暫的；轉瞬即逝的",
            context: "Fame is ephemeral, but craft endures.",
            explanation: "Lasting for a very short time; describes things that fade quickly, often with a wistful, literary tone.",
            partOfSpeech: "adj.",
            bookTitle: "On Writing Well",
            chapterTitle: "Chapter 3 · Simplicity"
        )
        entry.difficultyTier = "advanced"
        entry.reviewExamples = [
            "The ephemeral beauty of cherry blossoms draws crowds each spring.",
            "Social media trends are notoriously ephemeral.",
        ]
        entry.collocations = ["ephemeral nature", "ephemeral pleasure"]
        return entry
    }

    private static func minimalEntry() -> VocabularyEntry {
        VocabularyEntry(
            word: "terse",
            translation: "簡潔的",
            context: "His terse reply ended the discussion.",
            partOfSpeech: "adj.",
            bookTitle: "Sample Book"
        )
    }

    private static func richDocument() -> CardDocument {
        CardDocumentBuilder.build(
            word: "ephemeral",
            translation: "短暫的；轉瞬即逝的",
            partOfSpeech: "adj.",
            difficultyTier: "advanced",
            reviewModeTitle: "辨識",
            examples: ["The ephemeral beauty of cherry blossoms draws crowds each spring."],
            sourceContext: "Fame is ephemeral, but craft endures.",
            bookTitle: "On Writing Well",
            chapterTitle: "Chapter 3 · Simplicity",
            explanation: "Lasting for a very short time; describes things that fade quickly, often with a wistful, literary tone.",
            collocations: ["ephemeral nature", "ephemeral pleasure"],
            showsSourceContext: true
        )
    }

    private static func minimalDocument() -> CardDocument {
        CardDocumentBuilder.build(
            word: "terse",
            translation: "簡潔的",
            partOfSpeech: "adj.",
            difficultyTier: nil,
            reviewModeTitle: "辨識",
            examples: [],
            sourceContext: "His terse reply ended the discussion.",
            bookTitle: "Sample Book",
            chapterTitle: nil,
            explanation: nil,
            collocations: [],
            showsSourceContext: true
        )
    }
}
#endif
