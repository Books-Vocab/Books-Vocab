#if os(iOS)
import Foundation

enum KnowledgeGraphCopy {
    static var loginTitle: String { L10n.string("需登入帳號") }
    static var loginDescription: String { L10n.string("請至設定中登入以查閱您的知識關聯。") }
    static var loadingTitle: String { L10n.string("正在載入關聯圖...") }
    static var loadingDescription: String { L10n.string("正在向伺服器拉取知識連結與節點資訊。") }
    static var errorTitle: String { L10n.string("載入失敗") }
    static var retryTitle: String { L10n.string("重試") }
    static var noLinksTitle: String { L10n.string("尚無知識連結") }
    static var noLinksDescription: String {
        L10n.string("持續收錄相關單字，系統會自動建立關聯。或在設定中開啟「孤立節點」以瀏覽所有單字。")
    }
    static var noLinkedNodesTitle: String { L10n.string("目前無已連結節點") }
    static var noLinkedNodesDescription: String {
        L10n.string("可在設定中開啟「孤立節點」以瀏覽所有已收錄單字。")
    }
    static var emptyGraphTitle: String { L10n.string("知識圖譜為空") }
    static var emptyGraphDescription: String { L10n.string("尚無已收錄單字，或尚未與伺服器同步。") }

    static var settingsTitle: String { L10n.string("關聯圖") }
    static var resetTitle: String { L10n.string("重設") }
    static var forcesSectionTitle: String { L10n.string("力") }
    static var centerForceTitle: String { L10n.string("向心力") }
    static var repelForceTitle: String { L10n.string("排斥力") }
    static var linkForceTitle: String { L10n.string("連結強度") }
    static var linkDistanceTitle: String { L10n.string("連結距離") }
    static var displaySectionTitle: String { L10n.string("顯示") }
    static var nodeSizeTitle: String { L10n.string("節點大小") }
    static var linkThicknessTitle: String { L10n.string("連結粗細") }
    static var isolatedNodesTitle: String { L10n.string("孤立節點") }

    static var safeTitle: String { L10n.string("安全") }
    static var dueTitle: String { L10n.string("到期") }
    static var overdueTitle: String { L10n.string("逾期") }
    static var unlearnedArchivedTitle: String { L10n.string("未學習 / 封存") }
}
#endif
