import Testing
@testable import BooksAndVocab

struct SettingsAPIKeyPresentationTests {
    @Test func management_row_is_visible_only_for_logged_in_pro_accounts() {
        #expect(SettingsAPIKeyPresentation.shouldShowManagement(isLoggedIn: true, isProActive: true))
        #expect(!SettingsAPIKeyPresentation.shouldShowManagement(isLoggedIn: true, isProActive: false))
        #expect(!SettingsAPIKeyPresentation.shouldShowManagement(isLoggedIn: false, isProActive: true))
        #expect(!SettingsAPIKeyPresentation.shouldShowManagement(isLoggedIn: false, isProActive: false))
    }

    @Test func user_facing_copy_is_localized_through_the_settings_copy_boundary() {
        #expect(SettingsAPIKeyCopy.rowTitle == L10n.string("外部 API 金鑰"))
        #expect(SettingsAPIKeyCopy.navigationTitle == L10n.string("API 金鑰"))
        #expect(SettingsAPIKeyCopy.createButtonTitle == L10n.string("建立 API 金鑰"))
    }
}
