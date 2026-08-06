#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the higher-level Settings section blocks:
/// `SettingsReviewSection` (full 複習節奏 screen) and `SettingsPreferencesSection`
/// (偏好 card). Review/preference state is sourced from UI World `settings.*`
/// seeds so Catalog, UITest, and demo datasets share the same user-state owner.
///
/// `SettingsReviewSection` reads `\.reviewSettingsStore`; we inject an isolated
/// `ReviewSettingsStore(previewSettings:)` per scenario from inside a View body
/// scene so any actor isolation on store init is honoured.
enum SettingsSectionsScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Review Section (複習節奏)
        playbook.addScenarios(of: "Settings Sections · Review") {
            Scenario("寬鬆模式", layout: .fill) {
                ReviewSectionScene(fixtureID: .subscriptionFree)
            }
            Scenario("密集模式", layout: .fill) {
                ReviewSectionScene(fixtureID: .preferencesAutoSyncOff)
            }
            Scenario("自訂模式 / 展開參數", layout: .fill) {
                ReviewSectionScene(fixtureID: .accountLongIdentity)
            }
            Scenario("已凍結進度", layout: .fill) {
                ReviewSectionScene(fixtureID: .preferencesLoggedOutNoSync)
            }
        }

        // MARK: Preferences Section (偏好)
        playbook.addScenarios(of: "Settings Sections · Preferences") {
            Scenario("含自動同步", layout: .fill) {
                PreferencesSectionScene(fixtureID: .subscribedActive)
            }
            Scenario("自動同步關閉", layout: .fill) {
                PreferencesSectionScene(fixtureID: .preferencesAutoSyncOff)
            }
            Scenario("未登入 / 無同步列", layout: .fill) {
                PreferencesSectionScene(fixtureID: .preferencesLoggedOutNoSync)
            }
        }

        // MARK: Other Section (其他 — 同步狀態 / 額度 / 外部連結)
        //
        // 同步進行中的形態在此之前**完全沒有 catalog 覆蓋**（五個 settings fixture
        // 的 `isSyncing` 全是 false），所以逐步清單與進度條的視覺回歸沒人守。
        playbook.addScenarios(of: "Settings Sections · Other") {
            Scenario("閒置（收合）", layout: .fill) {
                OtherSectionScene(fixtureID: .subscribedActive, progress: .idle)
            }
            Scenario("同步中 / 逐步進度", layout: .fill) {
                OtherSectionScene(fixtureID: .subscribedActive, progress: .midway)
            }
            Scenario("同步中 / 含失敗與略過", layout: .fill) {
                OtherSectionScene(fixtureID: .subscribedActive, progress: .mixed)
            }
        }
    }
}

// MARK: - Scene harnesses

/// Body is main-actor isolated, so the `ReviewSettingsStore` init runs in a
/// safe context regardless of its isolation.
private struct ReviewSectionScene: View {
    let fixtureID: SettingsFixtureID

    private var settings: ReviewSettings {
        SettingsFixtures.reviewSettings(for: fixtureID)
    }

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                SettingsReviewSection()
            }
        }
        .environment(\.reviewSettingsStore, ReviewSettingsStore(previewSettings: settings))
        .environmentObject(AppAppearanceStore.preview)
    }
}

private struct PreferencesSectionScene: View {
    let fixtureID: SettingsFixtureID

    private var state: SettingsPresenterState.PreferencesSection {
        SettingsFixtures.state(for: fixtureID).preferences
    }

    var body: some View {
        AppThemeContainer {
            ScrollView {
                SettingsPreferencesSection(
                    state: state,
                    actions: Self.noopActions,
                    onShowTranslationLanguage: {},
                    onShowReviewSettings: {}
                )
                .padding()
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    private static let noopActions = SettingsPresenterActions(
        dismiss: {},
        loginWithGoogle: {},
        loginWithApple: {},
        logout: {},
        manualLogin: {},
        useProductionBackend: {},
        useLocalBackend: {},
        selectLanguage: { _ in },
        selectAppearance: { _ in },
        showSubscriptionPaywall: {},
        requestDeleteAccount: {},
        openPrivacyPolicy: {},
        openTermsOfService: {},
        openSupport: {},
        requestAppRating: {},
        resync: {},
        toggleAutoSync: { _ in },
        exportVocabularyCSV: {}
    )
}

/// 「其他」section 的 catalog 場景。
///
/// 使用者狀態（版本 / 登入 / 上次同步時間）照慣例來自 UI World seed；
/// **同步進度不是使用者狀態**——它是一輪同步的瞬時值，沒有、也不該有 fixture
/// 欄位，所以在這裡就地組一個 `SyncProgressStore` 注入。`isSyncing` 同理由就地
/// 覆寫，不為了一個布林去回填兩份 world JSON。
private struct OtherSectionScene: View {
    enum Progress {
        case idle
        case midway
        case mixed
    }

    let fixtureID: SettingsFixtureID
    let progress: Progress

    var body: some View {
        AppThemeContainer {
            ScrollView {
                SettingsOtherSection(
                    syncSummary: syncSummary,
                    bookSync: nil,
                    isLoggedIn: true,
                    version: SettingsFixtures.state(for: fixtureID).about.version,
                    actions: Self.noopActions
                )
                .padding()
            }
        }
        .environment(\.syncProgressStore, store)
        .environmentObject(AppAppearanceStore.preview)
    }

    private var syncSummary: SettingsPresenterState.SyncSummaryState {
        let seeded = SettingsFixtures.state(for: fixtureID).syncSummary
        return SettingsPresenterState.SyncSummaryState(
            isConnected: seeded?.isConnected ?? true,
            isSyncing: progress != .idle,
            summaryText: seeded?.summaryText ?? "",
            lastSyncedText: seeded?.lastSyncedText
        )
    }

    private var store: SyncProgressStore {
        let store = SyncProgressStore()
        guard progress != .idle else { return store }
        store.begin(stepIDs: KGService.syncStepIDs(podcastEnabled: true) + [.status])
        store.apply(.finished(.push, status: .done, detail: L10n.format("已送出 %@ 筆", "12")))
        store.apply(.started(.pull))
        store.apply(.advanced(.pull, current: 340, total: 960, detail: ""))
        if progress == .mixed {
            store.apply(.finished(.pull, status: .done, detail: L10n.format("同步 %@ 筆", "18")))
            store.apply(.finished(.dictionary, status: .skipped, detail: L10n.string("此伺服器尚未提供字典卡")))
            store.apply(.started(.reviewEvents))
            store.apply(.finished(.reviewEvents, status: .error, detail: L10n.string("sync.failure.reason.unknown")))
            store.apply(.started(.podcast))
        }
        return store
    }

    private static let noopActions = SettingsPresenterActions(
        dismiss: {},
        loginWithGoogle: {},
        loginWithApple: {},
        logout: {},
        manualLogin: {},
        useProductionBackend: {},
        useLocalBackend: {},
        selectLanguage: { _ in },
        selectAppearance: { _ in },
        showSubscriptionPaywall: {},
        requestDeleteAccount: {},
        openPrivacyPolicy: {},
        openTermsOfService: {},
        openSupport: {},
        requestAppRating: {},
        resync: {},
        toggleAutoSync: { _ in },
        exportVocabularyCSV: {}
    )
}
#endif
