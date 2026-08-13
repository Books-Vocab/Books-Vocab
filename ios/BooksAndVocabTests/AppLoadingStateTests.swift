#if os(iOS)
import Testing
@testable import BooksAndVocab

struct AppLoadingStateTests {
    @Test func progressIndicatorClampsInvalidValuesBeforeRendering() {
        #expect(AppLoadingIndicator.progress(-0.2).normalizedProgress == 0)
        #expect(AppLoadingIndicator.progress(0.42).normalizedProgress == 0.42)
        #expect(AppLoadingIndicator.progress(1.4).normalizedProgress == 1)
        #expect(AppLoadingIndicator.progress(.nan).normalizedProgress == 0)
    }
}
#endif
