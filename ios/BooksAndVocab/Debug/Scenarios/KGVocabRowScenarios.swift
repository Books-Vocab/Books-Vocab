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
                KGVocabRowScene(fixture: .default)
            }
            Scenario("Highlighted", layout: .compressed) {
                KGVocabRowScene(fixture: .highlighted)
            }
            Scenario("Selecting · unselected", layout: .compressed) {
                KGVocabRowScene(fixture: .selectingUnselected)
            }
            Scenario("Selecting · selected", layout: .compressed) {
                KGVocabRowScene(fixture: .selectingSelected)
            }
            Scenario("Long translation", layout: .compressed) {
                KGVocabRowScene(fixture: .longTranslation)
            }
        }
    }
}

// MARK: - Fixtures

private enum KGVocabRowFixture: CaseIterable {
    case `default`
    case highlighted
    case selectingUnselected
    case selectingSelected
    case longTranslation

    var entryIndex: Int {
        switch self {
        case .default:
            return 0
        case .highlighted:
            return 1
        case .selectingUnselected:
            return 2
        case .selectingSelected:
            return 3
        case .longTranslation:
            return 4
        }
    }

    var isSelecting: Bool {
        switch self {
        case .selectingUnselected, .selectingSelected:
            return true
        case .default, .highlighted, .longTranslation:
            return false
        }
    }

    var isSelected: Bool {
        switch self {
        case .selectingSelected:
            return true
        case .default, .highlighted, .selectingUnselected, .longTranslation:
            return false
        }
    }

    var isHighlighted: Bool {
        switch self {
        case .highlighted:
            return true
        case .default, .selectingUnselected, .selectingSelected, .longTranslation:
            return false
        }
    }
}

// MARK: - Scene harness

/// `@MainActor` body so the `@Model` `VocabularyEntry` is constructed on the
/// main actor before `KGVocabRow` reads it.
private struct KGVocabRowScene: View {
    let entry: VocabularyEntry
    let isSelecting: Bool
    let isSelected: Bool
    let isHighlighted: Bool

    init(fixture: KGVocabRowFixture) {
        entry = MainActor.assumeIsolated {
            Self.entry(for: fixture)
        }
        isSelecting = fixture.isSelecting
        isSelected = fixture.isSelected
        isHighlighted = fixture.isHighlighted
    }

    var body: some View {
        AppThemeContainer {
            KGVocabRow(
                entry: entry,
                allowsSelection: true,
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

    private static func seed() -> UIWorldVocabularySeed {
        FixtureDatasetStore.requireVocabularySeed(for: .kgVocabRow)
    }

    @MainActor
    private static func entry(for fixture: KGVocabRowFixture) -> VocabularyEntry {
        let seed = seed()
        precondition(
            seed.entries.count == KGVocabRowFixture.allCases.count,
            "UI World vocabulary.kgVocabRow expected \(KGVocabRowFixture.allCases.count) entries, got \(seed.entries.count)"
        )
        return UITestFixtureSeed.makeVocabularyEntry(from: seed.entries[fixture.entryIndex], notebookId: seed.notebookRemoteId)
    }
}
#endif
