#if os(iOS)
import Testing
@testable import BooksAndVocab

struct AppFilterSurfaceTests {
    @Test func sharedFilterStylesOptIntoSystemGlass() {
        #expect(AppTabSelectorStyle.themed(AppTheme.light).usesSystemGlass)
        #expect(AppTabSelectorStyle.vocab(AppSkin.previewNeutral).usesSystemGlass)
    }
}
#endif
