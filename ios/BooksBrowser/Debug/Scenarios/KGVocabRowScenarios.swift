#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `KGVocabRow` — 詞庫列表的單一單字列。
///
/// `KGVocabRow` 吃一個 `@Model` `VocabularyEntry`（@MainActor 構造），其餘為純值/閉包。
/// `VocabularyEntry` 必須在 `@MainActor` View body 內構造，因此包進 `KGVocabRowScene`。
/// row 透過 `.reviewSettingsStore` env 計算複習進度；注入 `ReviewSettingsStore`
/// preview store 以確保確定性渲染（避免讀 `.shared` 的真實偏好）。
enum KGVocabRowScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "KG Vocab Row") {
            Scenario("Default", layout: .compressed) {
                KGVocabRowScene(
                    word: "meticulous",
                    translation: "一絲不苟的；非常仔細的",
                    partOfSpeech: "adj."
                )
            }
            Scenario("Highlighted", layout: .compressed) {
                KGVocabRowScene(
                    word: "nuance",
                    translation: "細微差異；語氣層次",
                    partOfSpeech: "n.",
                    isHighlighted: true
                )
            }
            Scenario("Selecting · unselected", layout: .compressed) {
                KGVocabRowScene(
                    word: "ephemeral",
                    translation: "短暫的；轉瞬即逝的",
                    partOfSpeech: "adj.",
                    isSelecting: true,
                    isSelected: false
                )
            }
            Scenario("Selecting · selected", layout: .compressed) {
                KGVocabRowScene(
                    word: "serendipity",
                    translation: "機緣巧合",
                    partOfSpeech: "n.",
                    isSelecting: true,
                    isSelected: true
                )
            }
            Scenario("Long translation", layout: .compressed) {
                KGVocabRowScene(
                    word: "quintessential",
                    translation: "典型的；最具代表性的；體現某事物本質的最完美範例",
                    partOfSpeech: "adj."
                )
            }
        }
    }
}

// MARK: - Scene harness

/// `@MainActor` body so the `@Model` `VocabularyEntry` is constructed on the
/// main actor before `KGVocabRow` reads it.
private struct KGVocabRowScene: View {
    let word: String
    let translation: String
    let partOfSpeech: String
    var isSelecting: Bool = false
    var isSelected: Bool = false
    var isHighlighted: Bool = false

    var body: some View {
        let entry = VocabularyEntry(
            word: word,
            translation: translation,
            context: "It was a \(word) example that lingered in memory.",
            partOfSpeech: partOfSpeech,
            bookTitle: "Sample Book",
            chapterTitle: "第一章"
        )
        AppThemeContainer {
            KGVocabRow(
                entry: entry,
                isSelecting: isSelecting,
                isSelected: isSelected,
                isHighlighted: isHighlighted,
                onTap: {},
                onToggleSelection: {},
                onLongPress: {}
            )
            .padding(16)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
