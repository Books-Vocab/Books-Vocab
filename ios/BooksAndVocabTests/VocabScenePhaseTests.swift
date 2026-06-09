#if os(iOS)
import Testing
@testable import BooksAndVocab

@Suite("VocabScenePhase")
struct VocabScenePhaseTests {
    @Test func errorPhaseCarriesOptionalDescription() {
        let phase = VocabScenePhase.error(
            title: "無法載入",
            systemImage: "exclamationmark.triangle",
            description: "網路連線中斷",
            retryAction: {}
        )

        guard case .error(_, _, let description, _) = phase else {
            Issue.record("expected an error phase")
            return
        }
        #expect(description == "網路連線中斷")
    }
}
#endif
