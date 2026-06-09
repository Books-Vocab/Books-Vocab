#if os(iOS)
import Testing
@testable import BooksAndVocab

struct KnowledgeGraphCopyTests {

    @Test func emptyStateCopy_staysStable() {
        #expect(KnowledgeGraphCopy.loginTitle == L10n.string("需登入帳號"))
        #expect(KnowledgeGraphCopy.loadingTitle == L10n.string("正在載入關聯圖..."))
        #expect(KnowledgeGraphCopy.errorTitle == L10n.string("載入失敗"))
        #expect(KnowledgeGraphCopy.retryTitle == L10n.string("重試"))
        #expect(KnowledgeGraphCopy.noLinksTitle == L10n.string("尚無知識連結"))
        #expect(KnowledgeGraphCopy.noLinkedNodesTitle == L10n.string("目前無已連結節點"))
        #expect(KnowledgeGraphCopy.emptyGraphTitle == L10n.string("知識圖譜為空"))
    }

    @Test func settingsOverlayCopy_staysStable() {
        #expect(KnowledgeGraphCopy.settingsTitle == L10n.string("關聯圖"))
        #expect(KnowledgeGraphCopy.resetTitle == L10n.string("重設"))
        #expect(KnowledgeGraphCopy.forcesSectionTitle == L10n.string("力"))
        #expect(KnowledgeGraphCopy.displaySectionTitle == L10n.string("顯示"))
        #expect(KnowledgeGraphCopy.isolatedNodesTitle == L10n.string("孤立節點"))
    }

    @Test func legendCopy_staysStable() {
        #expect(KnowledgeGraphCopy.safeTitle == L10n.string("安全"))
        #expect(KnowledgeGraphCopy.dueTitle == L10n.string("到期"))
        #expect(KnowledgeGraphCopy.overdueTitle == L10n.string("逾期"))
        #expect(KnowledgeGraphCopy.unlearnedArchivedTitle == L10n.string("未學習 / 封存"))
    }
}
#endif
