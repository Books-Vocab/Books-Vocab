import SwiftUI
import SwiftData

struct KnowledgeGraphView: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.detailRouter) private var detailRouter
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore
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
        .onChange(of: coordinator.selectedEntry) { _, entry in
            if let entry, detailRouter != nil {
                detailRouter?.showWordDetail(entry, allEntries: allEntries)
                coordinator.selectedEntry = nil
            }
        }
        .toastSheet(item: Binding(
            get: { detailRouter == nil ? coordinator.selectedEntry : nil },
            set: { coordinator.selectedEntry = $0 }
        )) { entry in
            WordDetailSheet(entry: entry, allEntries: allEntries)
                .appSheet(.large)
        }
        .enableInjection()
    }

    private var presenterState: KnowledgeGraphPresenter.State {
        let reviewNow = reviewSettingsStore.settings.reviewReferenceDate()
        let nodes = KnowledgeGraphPresentation.nodes(
            from: allEntries,
            links: coordinator.links,
            showIsolatedNodes: coordinator.showsIsolatedNodes,
            now: reviewNow
        )
        let edges = KnowledgeGraphPresentation.edges(
            from: coordinator.links,
            validNodeIDs: Set(nodes.map(\.id))
        )

        let syncedEntryCount = allEntries.reduce(into: 0) { acc, entry in
            if entry.isSynced, entry.syncAction != .delete, !entry.isArchived, entry.kgCardId != nil {
                acc += 1
            }
        }
        return .init(
            emptyState: KnowledgeGraphPresentation.emptyState(
                isLoggedIn: authManager.isLoggedIn,
                isLoading: coordinator.isLoading,
                errorMessage: coordinator.errorMessage,
                nodes: nodes,
                syncedEntryCount: syncedEntryCount,
                linkCount: coordinator.links.count,
                showsIsolatedNodes: coordinator.showsIsolatedNodes,
                onRetry: reloadGraphData
            ),
            nodes: nodes,
            edges: edges,
            graphTheme: KnowledgeGraphPresentation.theme(for: appSkin),
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

    /// Synchronous entry point for the error-state retry button — the only
    /// in-place way to re-run a failed `loadGraphData` without leaving the tab.
    /// `AppEmptyStateAction.handler` is sync, so the async load is bridged
    /// through a `Task`.
    private func reloadGraphData() {
        Task { await coordinator.loadGraphData(authManager: authManager, kgService: kgService) }
    }
}
