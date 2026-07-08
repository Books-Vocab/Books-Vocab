#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the full `KnowledgeGraphView` surface (知識圖譜).
///
/// Vocabulary rows, graph links, and auth all come from UI World. The catalog
/// disables the view's remote graph `.task` and injects manifest-derived links,
/// so snapshots never depend on network, demo mode, or simulator session state.
enum KnowledgeGraphViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Knowledge Graph View") {
            // Wrapped in CatalogGraphSnapshotScene: the graph renders in a
            // WKWebView, which `layer.render(in:)` snapshots cannot see — the
            // freezer settles the d3 layout and swaps in a rasterized overlay
            // before the snapshot is taken. The empty scene needs no wrapper
            // (no webview is ever mounted in its empty state).
            Scenario("Populated graph", layout: .fill) { context in
                CatalogGraphSnapshotScene(context: context) {
                    KnowledgeGraphViewScene(fixture: .populated)
                }
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
            return .init(visibleEntries: .atLeast(3), graphLinks: .atLeast(2), graphNodes: .atLeast(3), graphEdges: .atLeast(2))
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

        let graphLinks = Self.makeGraphLinks(from: visibleEntries, fixtureID: fixture.vocabularyID)
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

    private static let fixedNow: Date = {
        var comps = DateComponents()
        comps.year = 2026
        comps.month = 6
        comps.day = 1
        comps.hour = 12
        guard let date = Calendar.current.date(from: comps) else {
            preconditionFailure("Knowledge Graph catalog fixedNow date components are invalid")
        }
        return date
    }()

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

    private static func makeGraphLinks(
        from entries: [VocabularyEntry],
        fixtureID: UIWorldVocabularyFixtureID
    ) -> [KGGraphLink] {
        let cardIDs = Set(entries.compactMap(\.kgCardId))
        var links: [KGGraphLink] = []

        for entry in entries {
            guard let sourceID = entry.kgCardId else { continue }
            for summary in entry.graphLinksByKind.values.flatMap({ $0 }) where !summary.isHidden {
                guard cardIDs.contains(summary.cardId) else {
                    preconditionFailure(
                        "UI World vocabulary.\(fixtureID.rawValue) graph link \(summary.id) points to missing cardId \(summary.cardId)"
                    )
                }
                links.append(
                    KGGraphLink(
                        id: summary.id,
                        fromId: sourceID,
                        toId: summary.cardId,
                        kind: summary.kind,
                        confidence: summary.confidence,
                        reason: summary.reason
                    )
                )
            }
        }

        let uniqueIDs = Set(links.map(\.id))
        precondition(
            uniqueIDs.count == links.count,
            "UI World vocabulary.\(fixtureID.rawValue) graph links must have unique IDs"
        )
        return links
    }
}
#endif
