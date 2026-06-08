#if os(iOS)
import Testing
@testable import BooksBrowser

struct CardSectionsCopyTests {

    @Test func sharedCopyTitles_stayStable() {
        #expect(CardSectionsCopy.copyTitle == L10n.string("複製"))
        #expect(CardSectionsCopy.copiedTitle == L10n.string("已複製"))
    }

    @Test func sectionTitles_stayStable() {
        #expect(CardSectionsCopy.examplesTitle == L10n.string("例句"))
        #expect(CardSectionsCopy.sourceTitle == L10n.string("來源"))
        #expect(CardSectionsCopy.explanationTitle == L10n.string("教學筆記"))
        #expect(CardSectionsCopy.formsTitle == L10n.string("變化形"))
    }
}
#endif
