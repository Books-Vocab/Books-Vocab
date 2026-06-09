#if os(iOS)
import Testing
@testable import BooksAndVocab

struct SettingsAccountCopyTests {

    @Test func loginMarketingCopy_staysStable() {
        #expect(SettingsAccountCopy.sectionTitle == L10n.string("帳號"))
        #expect(SettingsAccountCopy.authenticatingTitle == L10n.string("正在驗證帳號…"))
        #expect(SettingsAccountCopy.marketingTitle == L10n.string("解鎖完整功能"))
        #expect(SettingsAccountCopy.marketingSubtitle == L10n.string("AI 翻譯・知識圖譜・雲端同步"))
    }

    @Test func authActionLabels_stayStable() {
        #expect(SettingsAccountCopy.googleLoginAccessibility == L10n.string("使用 Google 帳號登入"))
        #expect(SettingsAccountCopy.appleLoginAccessibility == L10n.string("使用 Apple 帳號登入"))
        #expect(SettingsAccountCopy.manualLoginPlaceholder == L10n.string("帳號 ID（手動）"))
        #expect(SettingsAccountCopy.manualLoginTitle == L10n.string("登入"))
        #expect(SettingsAccountCopy.logoutTitle == L10n.string("登出帳號"))
    }

    @Test func subscriptionRowTitle_usesActiveOverride() {
        #expect(
            SettingsAccountCopy.subscriptionRowTitle(isActive: true, planName: "Monthly")
                == L10n.string("Pro 已啟用")
        )
        #expect(
            SettingsAccountCopy.subscriptionRowTitle(isActive: false, planName: "Monthly")
                == "Monthly"
        )
        #expect(SettingsAccountCopy.upgradeTitle == L10n.string("升級"))
        #expect(SettingsAccountCopy.proBadgeTitle == L10n.string("PRO"))
        #expect(SettingsAccountCopy.proAccessibilityLabel == L10n.string("Pro 訂閱已啟用"))
    }
}
#endif
