#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the *inner* presenter `WordDetailPresenter` — driven by
/// a synthetic value-type `WordDetailPresenter.State` rather than the chrome
/// sheet (`WordDetailSheet`, already covered by `WordDetailScenarios`).
///
/// Exercises the seams `WordDetailSheet` cannot easily reach in isolation:
/// `showsChrome` on/off, presence of graph links (active + hidden), review
/// progress section, root-form / metadata footer, and the empty/minimal card.
///
/// 不掛 backend / SwiftData container:`CardPresentation` 僅有 `init(entry:)`,
/// 故由 in-memory `VocabularyEntry` 派生 presenter state;graph links 經
/// `graphLinksByKind` setter 直接注入。所有 closure 餵成 no-op,純視覺快照。
enum WordDetailPresenterScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Word Detail Presenter") {
            Scenario("Chrome · links + review", layout: .fill) {
                presenter(state: Self.richState(), showsChrome: true, withEdit: true)
            }
            Scenario("No chrome · links + review", layout: .fill) {
                presenter(state: Self.richState(), showsChrome: false, withEdit: false)
            }
            Scenario("Hidden links + minimal", layout: .fill) {
                presenter(state: Self.hiddenLinksState(), showsChrome: true, withEdit: true)
            }
            Scenario("Bare card (no links / progress)", layout: .fill) {
                presenter(state: Self.bareState(), showsChrome: true, withEdit: false)
            }
        }
    }

    // MARK: - Presenter helper

    /// `WordDetailPresenter` 是純值驅動 View(init 非 @MainActor),可在 Scenario
    /// closure 直接構造;`VocabularyEntry` 派生亦於 nonisolated static func 完成。
    private static func presenter(
        state: WordDetailPresenter.State,
        showsChrome: Bool,
        withEdit: Bool
    ) -> some View {
        let skin = AppSkin.previewNeutral
        return AppThemeContainer {
            WordDetailPresenter(
                state: state,
                isExcludedFromReader: false,
                showsChrome: showsChrome,
                onClose: {},
                onEdit: withEdit ? {} : nil,
                onLinkTapped: { _ in },
                onToggleExcludeFromReader: {},
                onAddLink: {},
                onDeleteLink: { _ in },
                onHideLink: { _ in },
                onUnhideLink: { _ in }
            )
            .appSkin(skin)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: - State fixtures

    private static func richState() -> WordDetailPresenter.State {
        let entry = Self.richEntry()
        entry.graphLinksByKind = [
            "contrasts_with": [
                link(id: "l1", cardId: "c1", word: "enduring", kind: "contrasts_with", label: "對比詞"),
                link(id: "l2", cardId: "c2", word: "permanent", kind: "contrasts_with", label: "對比詞"),
            ],
            "shares_usage": [
                link(id: "l3", cardId: "c3", word: "transient", kind: "shares_usage", label: "相近用法"),
            ],
        ]
        let card = entry.cardPresentation
        return WordDetailPresenter.State(
            title: entry.word,
            systemImage: "textformat.abc",
            card: card,
            rootForm: "ephemeral",
            metadataItems: [
                .init(icon: "book", text: "On Writing Well"),
                .init(icon: "calendar", text: "2026/06/01"),
                .init(icon: "tag", text: "advanced"),
            ],
            navigableLinkCardIDs: ["c1", "c3"],
            reviewProgress: VocabReviewProgress(
                statusLabel: "複習中",
                detailLabel: "3 / 5",
                ratio: 0.6
            )
        )
    }

    private static func hiddenLinksState() -> WordDetailPresenter.State {
        let entry = Self.minimalEntry()
        entry.graphLinksByKind = [
            "shares_usage": [
                link(id: "l4", cardId: "c4", word: "curt", kind: "shares_usage", label: "相近用法"),
                link(id: "l5", cardId: "c5", word: "laconic", kind: "shares_usage", label: "相近用法", hidden: true),
                link(id: "l6", cardId: "c6", word: "pithy", kind: "shares_usage", label: "相近用法", hidden: true),
            ],
        ]
        let card = entry.cardPresentation
        return WordDetailPresenter.State(
            title: entry.word,
            systemImage: "eye.slash",
            card: card,
            rootForm: nil,
            metadataItems: [.init(icon: "book", text: "Sample Book")],
            navigableLinkCardIDs: [],
            reviewProgress: nil
        )
    }

    private static func bareState() -> WordDetailPresenter.State {
        let entry = Self.minimalEntry()
        let card = entry.cardPresentation
        return WordDetailPresenter.State(
            title: entry.word,
            systemImage: "textformat.abc",
            card: card,
            rootForm: nil,
            metadataItems: [.init(icon: "book", text: "Sample Book")],
            navigableLinkCardIDs: [],
            reviewProgress: nil
        )
    }

    // MARK: - Model fixtures

    private static func link(
        id: String,
        cardId: String,
        word: String,
        kind: String,
        label: String,
        hidden: Bool = false
    ) -> KGCardLinkSummary {
        KGCardLinkSummary(
            id: id, cardId: cardId, word: word, kind: kind,
            label: label, confidence: 0.9, reason: "synthetic", hidden: hidden
        )
    }

    private static func richEntry() -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: "ephemeral",
            translation: "短暫的；轉瞬即逝的",
            context: "Fame is ephemeral, but craft endures.",
            explanation: "Lasting for a very short time; describes things that fade quickly.",
            partOfSpeech: "adj.",
            bookTitle: "On Writing Well",
            chapterTitle: "Chapter 3 · Simplicity"
        )
        entry.difficultyTier = "advanced"
        entry.rootForm = "ephemeral"
        entry.reviewExamples = [
            "The ephemeral beauty of cherry blossoms draws crowds each spring.",
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
}
#endif
