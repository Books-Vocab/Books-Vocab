#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `WordEditSheet` — the translation / teaching-note editor
/// reached by editing a vocabulary entry.
///
/// `WordEditSheet` only takes a `@Bindable VocabularyEntry`; it reads
/// `modelContext` lazily inside `save()`, so synthetic (non-persisted) entries
/// render the editor faithfully for snapshotting.
enum WordEditScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Word Edit") {
            Scenario("Populated", layout: .fill) {
                WordEditScene(
                    entry: WordEditScenarios.sampleEntry(
                        word: "serendipity",
                        translation: "機緣巧合",
                        explanation: "意外發現美好事物的能力；無心插柳的幸運。"
                    )
                )
            }

            Scenario("Empty explanation", layout: .fill) {
                WordEditScene(
                    entry: WordEditScenarios.sampleEntry(
                        word: "ephemeral",
                        translation: "短暫的",
                        explanation: nil
                    )
                )
            }

            Scenario("Long content stress", layout: .fill) {
                WordEditScene(
                    entry: WordEditScenarios.sampleEntry(
                        word: "verisimilitude",
                        translation: "逼真；貌似真實的特質，常用於形容文學或藝術作品營造的可信感",
                        explanation: String(repeating: "這個詞描述作品在細節與情境上達到的真實感，使讀者願意暫時擱置懷疑。", count: 6)
                    )
                )
            }

            Scenario("Long word title", layout: .fill) {
                WordEditScene(
                    entry: WordEditScenarios.sampleEntry(
                        word: "antidisestablishmentarianism",
                        translation: "反對廢除國教制度的立場",
                        explanation: "一個常被引用為英語中最長單字之一的政治神學名詞。"
                    )
                )
            }
        }
    }

    // MARK: - Fixtures

    private static func sampleEntry(word: String, translation: String, explanation: String?) -> VocabularyEntry {
        VocabularyEntry(
            word: word,
            translation: translation,
            context: "It was pure \(word) in the passage we read together.",
            explanation: explanation,
            partOfSpeech: "n.",
            bookTitle: "Sample Book",
            chapterTitle: "Chapter 1"
        )
    }
}

// MARK: - Scene harness

private struct WordEditScene: View {
    let entry: VocabularyEntry

    var body: some View {
        AppThemeContainer {
            WordEditSheet(entry: entry)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
