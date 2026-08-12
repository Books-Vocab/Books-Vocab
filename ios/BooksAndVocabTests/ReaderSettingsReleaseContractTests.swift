#if os(iOS)
import Testing
@testable import BooksAndVocab

struct ReaderSettingsReleaseContractTests {
    @Test func hitTestingDebugAvailabilityFollowsBuildConfiguration() {
        #if DEBUG
        #expect(ReaderDebugTools.isAvailable)
        #else
        #expect(!ReaderDebugTools.isAvailable)
        #endif
    }
}
#endif
