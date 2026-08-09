//
//  VocabularyListViewScenarios.swift
//  Books & Vocab
//
//  Catalog scenarios for `VocabularyListView` (a notebook's recorded vocab list).
//

#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `VocabularyListView`.
///
/// The view is `@Query`-backed (filter by the selected notebook id, sort by
/// `dateAdded` reverse) and branches on `authManager.isLoggedIn`:
/// - logged out → `loggedOutState` empty card + demo CTA;
/// - logged in → the real `KGVocabView` knowledge list, which itself queries
///   `knowledgeListPredicate` (syncStatus == synced, action != delete, not
///   archived).
///
/// Rows and auth state come from UI World `vocabulary.*` / `auth.*` seeds and
/// are materialized into a fresh in-memory store. Catalog uses a DEBUG seam to
/// skip non-render side effects (`healthCheck`, `KGVocabView.loadInitialData`)
/// so the full-screen surface stays deterministic and does not trigger real
/// sync/network work during snapshot runs.
enum VocabularyListViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Vocabulary List View") {
            Scenario("Populated · mixed sync states", layout: .fill) {
                VocabularyListViewScene(
                    fixture: .populated,
                    auth: .signedIn,
                    expected: .visibleAtLeast(4)
                )
            }
            Scenario("Single card", layout: .fill) {
                VocabularyListViewScene(
                    fixture: .single,
                    auth: .signedIn,
                    expected: .visibleExactly(1)
                )
            }
            Scenario("Long list (stress)", layout: .fill) {
                VocabularyListViewScene(
                    fixture: .long,
                    auth: .signedIn,
                    expected: .visibleAtLeast(40)
                )
            }
            Scenario("Empty · zero data", layout: .fill) {
                VocabularyListViewScene(
                    fixture: .empty,
                    auth: .signedIn,
                    expected: .visibleExactly(0)
                )
            }
            // Toolbar sync chrome active: a `.running` SyncCoordinator drives the
            // toolbar glyph's pulse + the pending-add fixtures drive the badge count,
            // so the web counterpart has a baseline for the "syncing · N pending"
            // toolbar state. Every other scenario injects the env-default `.ready`
            // coordinator, so this is the only one that exercises `isSyncing == true`.
            Scenario("Syncing · pending badge + active sync", layout: .fill) {
                VocabularyListViewScene(
                    fixture: .syncing,
                    auth: .signedIn,
                    expected: .visibleAtLeast(3),
                    syncPhase: .running
                )
            }
            Scenario("Logged out", layout: .fill) {
                VocabularyListViewScene(
                    fixture: .empty,
                    auth: .guest,
                    expected: .visibleExactly(0)
                )
            }
            // Dense reviewed-state inspection. Opens on the "已複習" tab with the review clock
            // frozen at the marketing anchor day, so the fresh-green cohort Phase 1
            // shaped (~16 low-count cards, ratio 0.001–0.038) sorts to the top of
            // the tab and the progress bars read as a green→amber gradient instead
            // of the flat all-expired list the default "複習優先" sort captured.
            Scenario("Reviewed · Dense", layout: .fill) {
                // Force light so this high-density state stays deterministic while
                // the reader marketing shot so the website set reads as one light
                // family (the Knowledge Graph WKWebView stays its own dark viz).
                // 門檻對齊凍結 world：`vocabulary.vocabListPopulated` 只有 5 筆
                // entry、4 筆可見。原本的 80 是行銷密度時代的宣告，凍結後補資料
                // 等於繼續餵 catalog（違反 catalog_scope.md §FROZEN 紅線），所以
                // 改的是斷言不是 world。對帳測試：
                // ops/tests/test_catalog_scene_expectations.py
                VocabularyListViewScene(
                    fixture: .reviewedMarketing,
                    auth: .signedIn,
                    expected: .visibleAtLeast(4),
                    initialReviewStates: [.reviewed],
                    reviewSettingsStore: VocabularyListViewScene.marketingFrozenStore
                )
                .environment(\.colorScheme, .light)
            }
        }
    }
}

// MARK: - Fixtures

private enum VocabularyListFixture {
    case populated
    case single
    case long
    case empty
    case syncing
    case reviewedMarketing

    var vocabularyID: UIWorldVocabularyFixtureID {
        switch self {
        case .populated:
            return .vocabListPopulated
        case .single:
            return .vocabListSingle
        case .long:
            return .vocabListLong
        case .empty:
            return .vocabListEmpty
        case .syncing:
            return .vocabListSyncing
        case .reviewedMarketing:
            // Full active primary account (same projection as the KG populated
            // graph), so the reviewed tab shows the whole learned cohort.
            return .vocabListPopulated
        }
    }
}

private enum VocabularyListExpectedShape {
    case visibleExactly(Int)
    case visibleAtLeast(Int)
}

// MARK: - Scene harness

/// `@MainActor` body so the in-memory container is seeded and the
/// `MainActor.assumeIsolated` env-default services resolve on the main actor
/// before `@Query` reads. Mirrors `ArchivedVocabScene`.
private struct VocabularyListViewScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth
    let syncCoordinator: SyncCoordinator
    let notebookId: String
    let initialReviewStates: Set<VocabularyReviewState>
    /// Optional frozen review clock. `nil` keeps the env-default store; the
    /// marketing scene injects a store paused at the marketing anchor day so the
    /// reviewed-tab ratios (and thus row colours / sort) are deterministic.
    let reviewSettingsStore: ReviewSettingsStore?

    init(
        fixture: VocabularyListFixture,
        auth authID: UIWorldAuthFixtureID,
        expected: VocabularyListExpectedShape,
        syncPhase: SyncPhase = .ready,
        initialReviewStates: Set<VocabularyReviewState> = [],
        reviewSettingsStore: ReviewSettingsStore? = nil
    ) {
        let seed = FixtureDatasetStore.requireVocabularySeed(for: fixture.vocabularyID)
        let authSeed = FixtureDatasetStore.requireAuthSeed(for: authID)
        do {
            let container = try ModelContainer(
                for: VocabularyEntry.self, Notebook.self, ReviewRecord.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            let entries = try MainActor.assumeIsolated {
                try UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)
            }
            Self.validate(entries, fixture: fixture, expected: expected)
            self.container = container
            self.auth = Self.makeAuth(from: authSeed)
            self.notebookId = seed.notebookRemoteId
        } catch {
            preconditionFailure("Failed to materialize UI World vocabulary.\(fixture.vocabularyID.rawValue) for VocabularyListViewScenarios: \(error)")
        }
        self.initialReviewStates = initialReviewStates
        self.reviewSettingsStore = reviewSettingsStore
        // Pin the toolbar's `isSyncing` to what the scenario declares. The env
        // default is a fresh `.ready` coordinator; setting `.phase` directly
        // (no real pipeline kicked off) renders the active-sync glyph state
        // deterministically without any network/SwiftData side effect.
        let coordinator = SyncCoordinator()
        coordinator.phase = syncPhase
        self.syncCoordinator = coordinator
    }

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                VocabularyListView(
                    notebookId: notebookId,
                    initialReviewStates: initialReviewStates
                )
                .environment(\.catalogTaskPolicy, .disabled)
                .modifier(ReviewClockInjector(store: reviewSettingsStore))
            }
            .modelContainer(container)
            .environment(\.authManager, auth)
            .environment(\.syncCoordinator, syncCoordinator)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    /// QA fallback anchor (2026-06-01 12:00); overridden by the frozen marketing
    /// clock when a marketing world is injected. Shared shape with the Knowledge
    /// Graph scene so both marketing shots read the same anchor day.
    private static let qaFallbackNow: Date = {
        var comps = DateComponents()
        comps.year = 2026
        comps.month = 6
        comps.day = 1
        comps.hour = 12
        guard let date = Calendar.current.date(from: comps) else {
            preconditionFailure("Vocabulary marketing catalog fallback now date components are invalid")
        }
        return date
    }()

    static let marketingFrozenStore: ReviewSettingsStore = {
        var settings = ReviewSettings.default
        settings.isProgressPaused = true
        settings.progressPausedAt = MarketingReviewClock.now(fallback: qaFallbackNow)
        return ReviewSettingsStore(previewSettings: settings)
    }()

    private static func validate(
        _ entries: [VocabularyEntry],
        fixture: VocabularyListFixture,
        expected: VocabularyListExpectedShape
    ) {
        let visible = entries.filter(\.shouldAppearInKnowledgeList)
        switch expected {
        case .visibleExactly(let count):
            guard visible.count == count else {
                preconditionFailure("UI World vocabulary.\(fixture.vocabularyID.rawValue) must declare \(count) visible vocabulary entries, got \(visible.count)")
            }
        case .visibleAtLeast(let count):
            guard visible.count >= count else {
                preconditionFailure("UI World vocabulary.\(fixture.vocabularyID.rawValue) must declare at least \(count) visible vocabulary entries, got \(visible.count)")
            }
        }
    }

    private static func makeAuth(from seed: UIWorldAuthSeed) -> CatalogPreviewAuth {
        CatalogPreviewAuth(
            isLoggedIn: seed.isLoggedIn,
            userId: seed.userId,
            token: seed.token,
            displayName: seed.displayName,
            userEmail: seed.email
        )
    }
}

/// Injects a frozen `ReviewSettingsStore` only when the scenario supplies one,
/// otherwise leaves the env-default store untouched (so the other Vocabulary
/// List scenarios keep their wall-clock review state).
private struct ReviewClockInjector: ViewModifier {
    let store: ReviewSettingsStore?

    func body(content: Content) -> some View {
        if let store {
            content.environment(\.reviewSettingsStore, store)
        } else {
            content
        }
    }
}
#endif
