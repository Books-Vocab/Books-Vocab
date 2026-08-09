#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the full `KnowledgeGraphView` surface (知識圖譜).
///
/// Vocabulary rows, graph links, and auth all come from UI World. The catalog
/// disables the view's remote graph `.task` and injects manifest-derived links,
/// so inspection never depends on network, demo mode, or simulator session state.
enum KnowledgeGraphViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Knowledge Graph View") {
            // Catalog runs inside a real simulator window, so WKWebView content
            // is rendered by the system compositor without a rasterization shim.
            Scenario("Populated graph", layout: .fill) {
                KnowledgeGraphViewScene(fixture: .populated)
            }
            Scenario("Logged out · empty graph", layout: .fill) {
                KnowledgeGraphViewScene(fixture: .loggedOutEmpty)
            }
        }
    }
}

// MARK: - Fixtures

private enum KnowledgeGraphViewFixture {
    case populated
    case loggedOutEmpty

    var vocabularyID: UIWorldVocabularyFixtureID {
        switch self {
        case .populated:
            return .knowledgeGraphPopulated
        case .loggedOutEmpty:
            return .knowledgeGraphEmpty
        }
    }

    var authID: UIWorldAuthFixtureID {
        switch self {
        case .populated:
            return .signedIn
        case .loggedOutEmpty:
            return .guest
        }
    }

    var expected: ExpectedShape {
        switch self {
        case .populated:
            // 全螢幕知識圖 = Stats 縮圖關聯圖的放大版（primary 全 active）。
            // 門檻對齊凍結 world：`vocabulary.knowledgeGraphPopulated` 是 4 筆
            // entry、兩對雙向 link（4 條）→ 4 節點 4 邊。原本 (80,50,80,50) 是
            // 舊展示輸出曾要求 80/50/80/50；agent tool 只驗這個 UI World
            // 實際宣告的最小結構，不再為展示密度擴充 fixture。
            return .init(visibleEntries: .atLeast(4), graphLinks: .atLeast(4), graphNodes: .atLeast(4), graphEdges: .atLeast(4))
        case .loggedOutEmpty:
            return .init(visibleEntries: .exactly(0), graphLinks: .exactly(0), graphNodes: .exactly(0), graphEdges: .exactly(0))
        }
    }
}

private struct ExpectedShape {
    enum Count {
        case exactly(Int)
        case atLeast(Int)

        func validate(_ actual: Int, label: String, fixtureID: UIWorldVocabularyFixtureID) {
            switch self {
            case .exactly(let expected):
                precondition(
                    actual == expected,
                    "UI World vocabulary.\(fixtureID.rawValue) expected exactly \(expected) \(label), got \(actual)"
                )
            case .atLeast(let minimum):
                precondition(
                    actual >= minimum,
                    "UI World vocabulary.\(fixtureID.rawValue) expected at least \(minimum) \(label), got \(actual)"
                )
            }
        }
    }

    let visibleEntries: Count
    let graphLinks: Count
    let graphNodes: Count
    let graphEdges: Count
}

// MARK: - Scene harness

private struct KnowledgeGraphViewScene: View {
    let entries: [VocabularyEntry]
    let graphLinks: [KGGraphLink]
    let auth: CatalogPreviewAuth
    let reviewSettingsStore: ReviewSettingsStore

    init(fixture: KnowledgeGraphViewFixture) {
        let seed = FixtureDatasetStore.requireVocabularySeed(for: fixture.vocabularyID)
        let authSeed = FixtureDatasetStore.requireAuthSeed(for: fixture.authID)
        let entries = seed.entries.map {
            UITestFixtureSeed.makeVocabularyEntry(from: $0, notebookId: seed.notebookRemoteId)
        }
        let visibleEntries = entries.filter(\.shouldAppearInKnowledgeList)
        fixture.expected.visibleEntries.validate(
            visibleEntries.count,
            label: "visible knowledge graph entries",
            fixtureID: fixture.vocabularyID
        )

        let graphLinks = UIWorldGraphLinks.makeGraphLinks(from: visibleEntries, fixtureID: fixture.vocabularyID)
        fixture.expected.graphLinks.validate(
            graphLinks.count,
            label: "manifest graph links",
            fixtureID: fixture.vocabularyID
        )

        let nodes = KnowledgeGraphPresentation.nodes(
            from: visibleEntries,
            links: graphLinks,
            now: Self.fixedNow
        )
        fixture.expected.graphNodes.validate(
            nodes.count,
            label: "graph nodes",
            fixtureID: fixture.vocabularyID
        )

        let edges = KnowledgeGraphPresentation.edges(from: graphLinks, validNodeIDs: Set(nodes.map(\.id)))
        fixture.expected.graphEdges.validate(
            edges.count,
            label: "graph edges",
            fixtureID: fixture.vocabularyID
        )

        self.entries = entries
        self.graphLinks = graphLinks
        self.auth = Self.makeAuth(from: authSeed, fixture: fixture)
        self.reviewSettingsStore = Self.frozenStore
    }

    var body: some View {
        AppThemeContainer {
            KnowledgeGraphView(
                allEntries: entries,
                initialGraphLinks: graphLinks,
                shouldLoadGraphData: false
            )
            .environment(\.authManager, auth)
            .environment(\.reviewSettingsStore, reviewSettingsStore)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // QA fallback anchor (2026-06-01 12:00) for a non-marketing render. A frozen
    // marketing world overrides it via `MarketingReviewClock` so the graph aligns
    // to the anchor day: with a stale 38-days-early anchor every card is
    // not-yet-due and every node renders green, flattening the ReviewGradient.
    private static let qaFallbackNow: Date = {
        var comps = DateComponents()
        comps.year = 2026
        comps.month = 6
        comps.day = 1
        comps.hour = 12
        guard let date = Calendar.current.date(from: comps) else {
            preconditionFailure("Knowledge Graph catalog fallback now date components are invalid")
        }
        return date
    }()

    private static var fixedNow: Date { MarketingReviewClock.now(fallback: qaFallbackNow) }

    private static let frozenStore: ReviewSettingsStore = {
        var settings = ReviewSettings.default
        settings.isProgressPaused = true
        settings.progressPausedAt = fixedNow
        return ReviewSettingsStore(previewSettings: settings)
    }()

    private static func makeAuth(from seed: UIWorldAuthSeed, fixture: KnowledgeGraphViewFixture) -> CatalogPreviewAuth {
        switch fixture {
        case .populated:
            guard seed.isLoggedIn else {
                preconditionFailure("UI World auth.\(fixture.authID.rawValue) must be logged in for populated Knowledge Graph catalog")
            }
        case .loggedOutEmpty:
            guard !seed.isLoggedIn else {
                preconditionFailure("UI World auth.\(fixture.authID.rawValue) must be logged out for empty Knowledge Graph catalog")
            }
        }
        return CatalogPreviewAuth(
            isLoggedIn: seed.isLoggedIn,
            userId: seed.userId,
            token: seed.token,
            displayName: seed.displayName,
            userEmail: seed.email
        )
    }

}
#endif
