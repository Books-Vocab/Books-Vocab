#if os(iOS)
import Testing
@testable import BooksBrowser

struct CardSectionsCopyTests {

    @Test func sharedCopyTitles_stayStable() {
        #expect(CardSectionsCopy.copyTitle == L10n.string("複製"))
        #expect(CardSectionsCopy.copiedTitle == L10n.string("已複製"))
    }

    @Test func sectionTitles_stayStable() {
        #expect(CardSectionsCopy.formsTitle == L10n.string("變化形"))
    }
}
#endif
