#if os(iOS)
import Testing
@testable import BooksAndVocab

struct BookshelfCopyTests {

    @Test func emptyState_copy_staysStable() {
        let copy = BookshelfCopy.emptyState

        #expect(copy.title == L10n.string("尚無書籍"))
        #expect(copy.description == L10n.string("匯入電子書開始閱讀（EPUB・TXT・MD・PDF）"))
        #expect(copy.guidanceText == L10n.string("點擊上方匯入按鈕加入你的第一本書"))
        #expect(copy.primaryActionTitle == L10n.string("匯入"))
        #expect(copy.loginActionTitle == L10n.string("登入帳號"))
        #expect(copy.demoActionTitle == L10n.string("體驗複習與圖譜"))
    }

    @Test func importErrorTitle_usesDiagnosisWhenPresent() {
        #expect(BookshelfCopy.importErrorTitle(diagnosis: nil) == L10n.string("匯入錯誤"))
        #expect(
            BookshelfCopy.importErrorTitle(diagnosis: "PDF")
                == L10n.format("匯入錯誤・%@", "PDF")
        )
    }

    @Test func toolbarAndBannerLabels_stayStable() {
        #expect(BookshelfCopy.navigationTitle == L10n.string("書庫"))
        #expect(BookshelfCopy.settingsAccessibilityLabel == L10n.string("設定"))
        #expect(BookshelfCopy.syncAccessibilityLabel == L10n.string("同步"))
        #expect(BookshelfCopy.importAccessibilityLabel == L10n.string("匯入"))
        #expect(BookshelfCopy.retryImportTitle == L10n.string("再試匯入"))
        #expect(BookshelfCopy.closeTitle == L10n.string("關閉"))
    }
}
#endif
