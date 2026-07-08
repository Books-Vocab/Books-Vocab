import Foundation
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

    // MARK: - Section visibility

    @Test func visibleCasesExcludePodcastsWhenDisabled() {
        #expect(AppPrimarySection.visibleCases(podcastEnabled: false) == [.bookshelf, .notebooks, .overview])
    }

    @Test func visibleCasesKeepFullOrderWhenEnabled() {
        #expect(AppPrimarySection.visibleCases(podcastEnabled: true) == AppPrimarySection.allCases)
    }

    // MARK: - Selection fallback

    @Test func resolvedSelectionFallsBackToBookshelfWhenPodcastsHidden() {
        #expect(AppPrimarySection.resolvedSelection(.podcasts, podcastEnabled: false) == .bookshelf)
    }

    @Test func resolvedSelectionKeepsVisibleSections() {
        #expect(AppPrimarySection.resolvedSelection(.podcasts, podcastEnabled: true) == .podcasts)
        #expect(AppPrimarySection.resolvedSelection(.overview, podcastEnabled: false) == .overview)
        #expect(AppPrimarySection.resolvedSelection(.notebooks, podcastEnabled: true) == .notebooks)
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
