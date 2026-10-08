#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
@Suite("KGVocabCoordinator banners")
struct KGVocabCoordinatorBannerTests {
    private final class StubDeleter: VocabularyDeleting, HealthChecking {
        func deleteCard(word: String, notebookId: String) async throws {}
        func batchDeleteCards(words: [String], notebookId: String) async throws -> KGBatchDeleteResponse {
            KGBatchDeleteResponse(deleted: words.count, deleted_words: words, not_found: [])
        }
        func healthCheck() async {}
    }

    @Test func dismissBannerClearsErrorAndSuccessMessages() {
        let coordinator = KGVocabCoordinator()
        coordinator.bannerError = .refresh(message: "offline", isRetryable: true, isNetworkRelated: true)
        coordinator.refreshSuccessMessage = "updated"

        coordinator.dismissBanner()

        #expect(coordinator.bannerError == nil)
        #expect(coordinator.errorMessage == nil)  // 衍生自 bannerError
        #expect(coordinator.refreshSuccessMessage == nil)
    }

    /// The top pill is an *event* (#2047): two identical outcomes in a row must
    /// notify twice, so every terminal result advances `noticeRevision` even when
    /// the resulting state value is unchanged.
    @Test func identicalRetryOutcomesEachAdvanceNoticeRevision() async throws {
        let container = try ModelContainer(
            for: VocabularyEntry.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let context = ModelContext(container)
        let coordinator = KGVocabCoordinator()
        let stub = StubDeleter()
        #expect(coordinator.noticeRevision == 0)

        await coordinator.retryPendingDeletes(pendingDeletes: [], kgService: stub, modelContext: context)
        #expect(coordinator.noticeRevision == 1)
        #expect(coordinator.refreshSuccessMessage == L10n.string("待刪除項目已同步"))

        await coordinator.retryPendingDeletes(pendingDeletes: [], kgService: stub, modelContext: context)
        #expect(coordinator.noticeRevision == 2)
        #expect(coordinator.refreshSuccessMessage == L10n.string("待刪除項目已同步"))
    }

    @Test func dismissingTheStateDoesNotEmitANotice() {
        let coordinator = KGVocabCoordinator()
        coordinator.bannerError = .archivePartial(message: "1/3")
        coordinator.dismissBanner()
        #expect(coordinator.noticeRevision == 0)
    }
}
#endif
