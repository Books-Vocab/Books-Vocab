#if os(iOS)
import Foundation

enum SettingsAccountCopy {
    static var sectionTitle: String { L10n.string("帳號") }
    static var authenticatingTitle: String { L10n.string("正在驗證帳號…") }
    static var marketingTitle: String { L10n.string("解鎖完整功能") }
    static var marketingSubtitle: String { L10n.string("AI 翻譯・知識圖譜・雲端同步") }
    static var googleLoginAccessibility: String { L10n.string("使用 Google 帳號登入") }
    static var appleLoginAccessibility: String { L10n.string("使用 Apple 帳號登入") }
    static var manualLoginPlaceholder: String { L10n.string("帳號 ID（手動）") }
    static var manualLoginTitle: String { L10n.string("登入") }
    static var manualLoginAccessibility: String { L10n.string("開發者登入") }
    static var authErrorTitle: String { L10n.string("登入暫時失敗") }
    static var logoutTitle: String { L10n.string("登出帳號") }
    static var upgradeTitle: String { L10n.string("升級") }
    static var activePlanTitle: String { L10n.string("Pro 已啟用") }
    static var proBadgeTitle: String { L10n.string("PRO") }
    static var proAccessibilityLabel: String { L10n.string("Pro 訂閱已啟用") }

    static func subscriptionRowTitle(isActive: Bool, planName: String) -> String {
        isActive ? activePlanTitle : planName
    }
}
#endif
