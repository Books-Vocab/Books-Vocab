import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

/// Pins the DEBUG-only podcast feature gate: Release builds must not surface
/// any podcast entry point (tab / sidebar / paywall marketing copy), while
/// DEBUG keeps the feature fully available.
struct PodcastFeatureGateTests {

    @Test func podcastFlagFollowsBuildConfiguration() {
        #if DEBUG
        #expect(KGFeatureFlags.podcastEnabled)
        #else
        #expect(!KGFeatureFlags.podcastEnabled)
        #endif
    }

    /// Explore 自 2026-08-05 起在**所有** configuration 曝光（原為 `#if DEBUG`）。
    /// 這條的用途是防回退：下面那些 visibility 測試全部傳明確 boolean，不讀旗標實值，
    /// 所以有人把 `#if DEBUG` 加回去時整個套件仍會全綠——除了這一條。
    @Test func exploreFlagIsOnInEveryConfiguration() {
        #expect(KGFeatureFlags.exploreEnabled)
    }

    // MARK: - Section visibility

    @Test func visibleCasesExcludePodcastsWhenDisabled() {
        #expect(
            AppPrimarySection.visibleCases(podcastEnabled: false, exploreEnabled: false)
                == [.bookshelf, .notebooks, .overview]
        )
    }

    @Test func visibleCasesKeepFullOrderWhenEnabled() {
        #expect(
            AppPrimarySection.visibleCases(podcastEnabled: true, exploreEnabled: true)
                == AppPrimarySection.allCases
        )
    }

    @Test func visibleCasesExcludeExploreWhenDisabled() {
        #expect(
            AppPrimarySection.visibleCases(podcastEnabled: true, exploreEnabled: false)
                == [.bookshelf, .podcasts, .notebooks, .overview]
        )
    }

    // MARK: - Selection fallback

    @Test func resolvedSelectionFallsBackToBookshelfWhenPodcastsHidden() {
        #expect(
            AppPrimarySection.resolvedSelection(.podcasts, podcastEnabled: false, exploreEnabled: true) == .bookshelf
        )
    }

    @Test func resolvedSelectionFallsBackToBookshelfWhenExploreHidden() {
        #expect(
            AppPrimarySection.resolvedSelection(.explore, podcastEnabled: true, exploreEnabled: false) == .bookshelf
        )
    }

    @Test func resolvedSelectionKeepsVisibleSections() {
        #expect(AppPrimarySection.resolvedSelection(.podcasts, podcastEnabled: true, exploreEnabled: true) == .podcasts)
        #expect(AppPrimarySection.resolvedSelection(.overview, podcastEnabled: false, exploreEnabled: false) == .overview)
        #expect(AppPrimarySection.resolvedSelection(.notebooks, podcastEnabled: true, exploreEnabled: true) == .notebooks)
        #expect(AppPrimarySection.resolvedSelection(.explore, podcastEnabled: true, exploreEnabled: true) == .explore)
    }
}

#if os(iOS)
/// Paywall surfaces must not advertise podcast features when the gate is off —
/// a hidden feature cannot appear in marketing / plan-comparison copy.
struct PodcastFeatureGatePaywallTests {

    @Test func paywallCatalogDropsPodcastRowWhenDisabled() {
        let disabled = SubscriptionPaywallFeatureCatalog.descriptors(podcastEnabled: false)
        #expect(!disabled.contains { $0.title.localizedCaseInsensitiveContains("podcast") })
        #expect(disabled.count == 7)
    }

    @Test func paywallCatalogKeepsPodcastRowWhenEnabled() {
        let enabled = SubscriptionPaywallFeatureCatalog.descriptors(podcastEnabled: true)
        #expect(enabled.contains { $0.title.localizedCaseInsensitiveContains("podcast") })
        #expect(enabled.count == 8)
    }

    /// The daily-AI-quota row is pinned as the last row by
    /// `SubscriptionPaywallFeatureCatalogTests`; gating must not reorder it.
    @Test func paywallCatalogKeepsQuotaRowLastRegardlessOfFlag() {
        #expect(SubscriptionPaywallFeatureCatalog.descriptors(podcastEnabled: false).last?.freeMark == .label("1x"))
        #expect(SubscriptionPaywallFeatureCatalog.descriptors(podcastEnabled: true).last?.freeMark == .label("1x"))
    }

    @Test func activeSubscriptionSummaryOmitsPodcastWhenDisabled() {
        let active = KGSubscriptionStatus(
            is_active: true,
            product_id: nil,
            plan_name: nil,
            price_display: nil,
            status: "active",
            is_trial: false,
            trial_days: nil,
            will_renew: true,
            expires_at: nil,
            source: "appstore",
            last_synced_at: nil
        )
        let disabledSummary = SubscriptionPresentation.summary(for: active, podcastEnabled: false)
        #expect(!disabledSummary.localizedCaseInsensitiveContains("podcast"))
        let enabledSummary = SubscriptionPresentation.summary(for: active, podcastEnabled: true)
        #expect(enabledSummary.localizedCaseInsensitiveContains("podcast"))
    }
}
#endif

// MARK: - Data-layer footprint

/// Release (`podcastEnabled == false`) must have **zero** podcast network/disk
/// footprint — the UI gate alone doesn't stop `backgroundSync`'s podcast
/// catalog leg (list fetch + cover downloads) which fires on post-login /
/// scenePhase→active / ⌘R / Settings manual sync. Pins the seam that
/// short-circuits it before any `PodcastSyncService` work happens.
@MainActor
struct PodcastDataLayerGateTests {

    @Test func backgroundCatalogSyncSkippedWhenDisabled() async {
        var ran = false
        let outcome = await KGService.runPodcastCatalogSyncIfEnabled(podcastEnabled: false) {
            ran = true
            return .completed
        }
        #expect(!ran)
        #expect(outcome == nil, "沒跑就沒有結果可回報；nil 讓 UI 知道這一列根本不存在")
    }

    @Test func backgroundCatalogSyncRunsWhenEnabled() async {
        var ran = false
        let outcome = await KGService.runPodcastCatalogSyncIfEnabled(podcastEnabled: true) {
            ran = true
            return .listFetchFailed
        }
        #expect(ran)
        #expect(outcome == .listFetchFailed, "結果必須原封傳回，否則 podcast 那一列永遠紅不起來")
    }
}

#if os(iOS)
/// `PodcastDownloadManager.configure` runs unconditionally at app launch; when
/// the podcast gate is off it must refuse the container so the manager stays
/// inert (no delegate persistence path, nothing to drive downloads).
@MainActor
struct PodcastDownloadManagerGateTests {

    private func makeContainer() throws -> ModelContainer {
        try ModelContainer(
            for: PodcastEpisode.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
    }

    @Test func configureIsRefusedWhenDisabled() throws {
        let manager = PodcastDownloadManager()
        manager.configure(modelContainer: try makeContainer(), podcastEnabled: false)
        #expect(!manager.isConfigured)
    }

    @Test func configureAppliesWhenEnabled() throws {
        let manager = PodcastDownloadManager()
        manager.configure(modelContainer: try makeContainer(), podcastEnabled: true)
        #expect(manager.isConfigured)
    }
}
#endif
