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

/// Entitlement-keyed key list loading (#2551): a late Pro grant must fetch and list keys,
/// a lapse must clear them, and a load superseded by a newer entitlement flip must not
/// clobber the newer result.
@MainActor
struct SettingsAPIKeyListLoaderTests {
    private func key(_ id: String) -> KGExternalAPIKey {
        KGExternalAPIKey(keyId: id, label: "Reader \(id)", createdAt: "2026-08-20T04:00:00Z", revokedAt: nil, apiKey: nil)
    }

    @Test func free_account_never_fetches_and_lists_nothing() async {
        let loader = SettingsAPIKeyListLoader()
        var fetchCount = 0
        await loader.reload(hasProAccess: false) {
            fetchCount += 1
            return []
        }
        #expect(fetchCount == 0)
        #expect(loader.keys.isEmpty)
    }

    @Test func late_pro_grant_fetches_and_lists_keys_without_reentry() async {
        let loader = SettingsAPIKeyListLoader()
        await loader.reload(hasProAccess: false) { [] }
        var fetchCount = 0
        await loader.reload(hasProAccess: true) {
            fetchCount += 1
            return [self.key("a")]
        }
        #expect(fetchCount == 1)
        #expect(loader.keys.map(\.keyId) == ["a"])
        #expect(!loader.isLoading)
    }

    @Test func pro_lapse_clears_displayed_keys() async {
        let loader = SettingsAPIKeyListLoader()
        await loader.reload(hasProAccess: true) { [self.key("a")] }
        #expect(loader.keys.count == 1)
        await loader.reload(hasProAccess: false) { [] }
        #expect(loader.keys.isEmpty)
        #expect(loader.errorMessage == nil)
    }

    @Test func superseded_load_cannot_clear_loading_of_newer_in_flight_load() async {
        let loader = SettingsAPIKeyListLoader()
        let stale = SuspendedFetch()
        let staleLoad = Task { await loader.reload(hasProAccess: true) { try await stale.fetch() } }
        for _ in 0..<100 where !stale.started { await Task.yield() }
        #expect(stale.started)

        // A newer entitlement-driven reload starts while the first fetch is still in flight.
        let newer = SuspendedFetch()
        let newerLoad = Task { await loader.reload(hasProAccess: true) { try await newer.fetch() } }
        for _ in 0..<100 where !newer.started { await Task.yield() }
        #expect(newer.started)

        // The superseded load completes first: it must publish nothing and must not clear
        // the loading flag that belongs to the still in-flight newer load.
        stale.resume(returning: [key("old")])
        await staleLoad.value
        #expect(loader.isLoading)
        #expect(loader.keys.isEmpty)

        newer.resume(returning: [key("new")])
        await newerLoad.value
        #expect(loader.keys.map(\.keyId) == ["new"])
        #expect(!loader.isLoading)
        #expect(loader.errorMessage == nil)
    }
}

@MainActor
private final class SuspendedFetch {
    private(set) var started = false
    private var continuation: CheckedContinuation<[KGExternalAPIKey], Error>?

    func fetch() async throws -> [KGExternalAPIKey] {
        started = true
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }

    func resume(returning keys: [KGExternalAPIKey]) {
        continuation?.resume(returning: keys)
    }
}
