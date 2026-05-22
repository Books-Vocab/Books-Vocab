#if DEBUG
import Playbook
import PlaybookUI
import SwiftUI

/// DEBUG-only Playbook catalog of KG SwiftUI surfaces.
///
/// 啟用方式:
/// 1. Xcode → Product → Scheme → Edit Scheme → Run → Arguments → Launch Arguments
///    加 `-catalog`
/// 2. ⌘R 跑 Debug build,app 啟動進 catalog 而非正常 UI
///
/// 截圖協作流程: simulator 跑著時用 `xcrun simctl io booted screenshot foo.png`,
/// 把 PNG 路徑貼給 Claude 即可協作視覺迭代。詳見 docs/sop/ios.md §Playbook Catalog。
struct CatalogScene: View {
    // Why: static let 確保 scenarios 只註冊一次 (Swift static init 是 thread-safe + lazy)。
    // 若改成 instance-level 每次 View init 都會重複註冊,Playbook 內部 storage
    // 會出現重複 entries。
    private static let playbook: Playbook = buildPlaybook()

    /// Build a fresh `Playbook` with all KG surface scenarios registered.
    /// Exposed (internal-access) so `BooksBrowserTests` can drive PlaybookSnapshot
    /// against the same surface set as the in-app catalog.
    static func buildPlaybook() -> Playbook {
        let pb = Playbook()
        TokenSheetScenarios.register(in: pb)
        NotebookDetailScenarios.register(in: pb)
        SettingsScenarios.register(in: pb)
        TodayReviewScenarios.register(in: pb)
        BookshelfScenarios.register(in: pb)
        WelcomeScenarios.register(in: pb)
        return pb
    }

    var body: some View {
        PlaybookCatalog(title: "KG Catalog", playbook: Self.playbook)
    }
}

#Preview {
    CatalogScene()
}
#endif
