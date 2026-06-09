#if os(iOS)
import Testing
@testable import BooksAndVocab

struct TodayReviewShortcutCatalogTests {

    @Test func completionHints_useExitAndHelp() {
        let hints = TodayReviewShortcutCatalog.activeHints(
            hasCurrentCard: false,
            revealStage: .front,
            isAutoPlaying: false,
            isAutoPlayPaused: false
        )

        #expect(hints.count == 2)
        #expect(hints[0] == .init(id: "esc", key: "Esc", label: L10n.string("返回"), isPrimary: true))
        #expect(hints[1] == .init(id: "help", key: "?", label: L10n.string("快捷鍵")))
    }

    @Test func reviewHints_switchExpandCopyByRevealStage() {
        let frontHints = TodayReviewShortcutCatalog.reviewHints(revealStage: .front)
        let backHints = TodayReviewShortcutCatalog.reviewHints(revealStage: .back)

        #expect(frontHints.first?.label == L10n.string("展開"))
        #expect(backHints.first?.label == L10n.string("收回"))
        #expect(frontHints.dropFirst() == backHints.dropFirst())
    }

    @Test func autoplayHints_switchPauseCopy() {
        let playing = TodayReviewShortcutCatalog.autoplayHints(isAutoPlayPaused: false)
        let paused = TodayReviewShortcutCatalog.autoplayHints(isAutoPlayPaused: true)

        #expect(playing.first?.label == L10n.string("暫停"))
        #expect(paused.first?.label == L10n.string("繼續"))
        #expect(playing.count == paused.count)
    }

    @Test func sessionAndNavigationHints_preserveExpectedHotkeys() {
        #expect(TodayReviewShortcutCatalog.navigationHints.map(\.key) == ["↑", "↓", "S", "D"])
        #expect(TodayReviewShortcutCatalog.sessionHints.map(\.key) == ["P", "Esc", "?"])
    }
}
#endif
