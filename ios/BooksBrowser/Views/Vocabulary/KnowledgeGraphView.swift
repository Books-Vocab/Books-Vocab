import SwiftUI
import SwiftData

struct KnowledgeGraphView: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    #if os(macOS)
    @Environment(\.macDetail) private var macDetail
    #endif
    let allEntries: [VocabularyEntry]
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
                linkThickness: $coordinator.linkThickness,
                showsIsolatedNodes: $coordinator.showsIsolatedNodes
            ),
            onToggleSettings: coordinator.toggleSettings,
            onResetForces: coordinator.resetForces,
            onNodeTapped: handleNodeTap
        )
        .task { await coordinator.loadGraphData(authManager: authManager, kgService: kgService) }
        #if os(macOS)
        .onChange(of: coordinator.selectedEntry) { _, entry in
            if let entry, let macDetail {
                macDetail.showWordDetail(entry, allEntries: allEntries)
                coordinator.selectedEntry = nil
            }
        }
        .toastSheet(item: Binding(
            get: { macDetail == nil ? coordinator.selectedEntry : nil },
            set: { coordinator.selectedEntry = $0 }
        )) { entry in
            WordDetailSheet(entry: entry, allEntries: allEntries)
                .appSheet(.large)
        }
        #else
        .toastSheet(item: $coordinator.selectedEntry) { entry in
            WordDetailSheet(entry: entry, allEntries: allEntries)
                .appSheet(.large)
        }
        #endif
    }

    private var presenterState: KnowledgeGraphPresenter.State {
        let nodes = KnowledgeGraphPresentation.nodes(
            from: allEntries,
            links: coordinator.links,
            showIsolatedNodes: coordinator.showsIsolatedNodes
        )
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
