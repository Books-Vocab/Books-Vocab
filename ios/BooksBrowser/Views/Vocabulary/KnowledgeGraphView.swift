import SwiftUI
import SwiftData

struct KnowledgeGraphView: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Query private var allEntries: [VocabularyEntry]
    @State private var coordinator = KnowledgeGraphCoordinator()

    var body: some View {
        KnowledgeGraphPresenter(
            state: presenterState,
            bindings: .init(
                centerForce: $coordinator.centerForce,
                repelForce: $coordinator.repelForce,
                linkForce: $coordinator.linkForce,
                linkDistance: $coordinator.linkDistance,
                nodeSize: $coordinator.nodeSize,
                linkThickness: $coordinator.linkThickness
            ),
            onToggleSettings: coordinator.toggleSettings,
            onResetForces: coordinator.resetForces,
            onNodeTapped: handleNodeTap
        )
        .task { await coordinator.loadGraphData(authManager: authManager, kgService: kgService) }
        .sheet(item: $coordinator.selectedEntry) { entry in
            WordDetailSheet(entry: entry)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
                .presentationContentInteraction(.scrolls)
        }
    }

    private var presenterState: KnowledgeGraphPresenter.State {
        let nodes = KnowledgeGraphPresentation.nodes(from: allEntries, links: coordinator.links)
        let edges = KnowledgeGraphPresentation.edges(
            from: coordinator.links,
            validNodeIDs: Set(nodes.map(\.id))
        )

        return .init(
            emptyState: KnowledgeGraphPresentation.emptyState(
                isLoggedIn: authManager.isLoggedIn,
                isLoading: coordinator.isLoading,
                errorMessage: coordinator.errorMessage,
                nodes: nodes
            ),
            nodes: nodes,
            edges: edges,
            graphTheme: KnowledgeGraphPresentation.theme(for: vocabSkin),
            forces: .init(
                repel: repelStrength,
                linkDistance: coordinator.linkDistance,
                linkStrength: linkStrength,
                centerStrength: centerStrength,
                baseNodeRadius: coordinator.nodeSize,
                collideRadius: collideRadius,
                linkThickness: coordinator.linkThickness
            ),
            showsSettings: coordinator.isShowingSettings
        )
    }

    private var repelStrength: Double { coordinator.repelForce * 400 }
    private var centerStrength: Double { coordinator.centerForce * 0.3 }
    private var linkStrength: Double { coordinator.linkForce * 2 }
    private var collideRadius: Double { coordinator.nodeSize * 1.5 }

    private func handleNodeTap(_ nodeID: String) {
        coordinator.handleNodeTap(nodeID, allEntries: allEntries)
    }
}
