import SwiftUI
import SwiftData

struct KnowledgeGraphView: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Query private var allEntries: [VocabularyEntry]

    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var isShowingSettings = false
    @State private var links: [KGGraphLink] = []
    @State private var selectedEntry: VocabularyEntry?

    @State private var centerForce: Double = 0.05
    @State private var repelForce: Double = 0.20
    @State private var linkForce: Double = 0.50
    @State private var linkDistance: Double = 50
    @State private var nodeSize: Double = 5.0
    @State private var linkThickness: Double = 1.0

    var body: some View {
        KnowledgeGraphPresenter(
            state: presenterState,
            bindings: .init(
                centerForce: $centerForce,
                repelForce: $repelForce,
                linkForce: $linkForce,
                linkDistance: $linkDistance,
                nodeSize: $nodeSize,
                linkThickness: $linkThickness
            ),
            onToggleSettings: toggleSettings,
            onResetForces: resetForces,
            onNodeTapped: handleNodeTap
        )
        .task { await loadGraphData() }
        .sheet(item: $selectedEntry) { entry in
            WordDetailSheet(entry: entry)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
    }

    private var presenterState: KnowledgeGraphPresenter.State {
        let nodes = KnowledgeGraphPresentation.nodes(from: allEntries, links: links)
        let edges = KnowledgeGraphPresentation.edges(
            from: links,
            validNodeIDs: Set(nodes.map(\.id))
        )

        return .init(
            emptyState: KnowledgeGraphPresentation.emptyState(
                isLoggedIn: authManager.isLoggedIn,
                isLoading: isLoading,
                errorMessage: errorMessage,
                nodes: nodes
            ),
            nodes: nodes,
            edges: edges,
            graphTheme: KnowledgeGraphPresentation.theme(for: vocabSkin),
            forces: .init(
                repel: repelStrength,
                linkDistance: linkDistance,
                linkStrength: linkStrength,
                centerStrength: centerStrength,
                baseNodeRadius: nodeSize,
                collideRadius: collideRadius,
                linkThickness: linkThickness
            ),
            showsSettings: isShowingSettings
        )
    }

    private var repelStrength: Double { repelForce * 400 }
    private var centerStrength: Double { centerForce * 0.3 }
    private var linkStrength: Double { linkForce * 2 }
    private var collideRadius: Double { nodeSize * 1.5 }

    private func toggleSettings() {
        withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
            isShowingSettings.toggle()
        }
    }

    private func resetForces() {
        centerForce = 0.05
        repelForce = 0.20
        linkForce = 0.50
        linkDistance = 50
        nodeSize = 5.0
        linkThickness = 1.0
    }

    private func handleNodeTap(_ nodeID: String) {
        selectedEntry = allEntries.first { $0.kgCardId == nodeID }
    }

    private func loadGraphData() async {
        guard authManager.isLoggedIn else { return }
        isLoading = true
        errorMessage = nil
        do {
            links = try await kgService.pullGraphLinks()
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }
}
