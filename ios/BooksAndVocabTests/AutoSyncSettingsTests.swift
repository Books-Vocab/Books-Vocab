import Foundation
import Testing
@testable import BooksAndVocab

@Suite("AutoSyncSettingsStore")
struct AutoSyncSettingsTests {
    @Test func defaultIsDisabled() {
        let store = AutoSyncSettingsStore(defaults: .makeSuite())
        #expect(store.isEnabled == false)
    }

    @Test func togglePersists() {
        let defaults = UserDefaults.makeSuite()
        let store = AutoSyncSettingsStore(defaults: defaults)
        store.setEnabled(true)
        #expect(store.isEnabled == true)

        let store2 = AutoSyncSettingsStore(defaults: defaults)
        #expect(store2.isEnabled == true)
    }

    @Test func thresholdIsFive() {
        #expect(AutoSyncSettingsStore.threshold == 5)
    }
}

private extension UserDefaults {
    static func makeSuite() -> UserDefaults {
        UserDefaults(suiteName: "test-auto-sync-\(UUID().uuidString)")!
    }
}
