import SwiftUI
import SwiftData

enum KnowledgeGraphNotebookScope {
    static func notebookID(for filter: NotebookFilter) -> String? {
        guard filter.selectedIds.count == 1 else { return nil }
        return filter.selectedIds.first
    }

    /// Notebooks whose links back the nodes in `entries` (all synced cards).
    static func notebookIDs(from entries: [VocabularyEntry]) -> [String] {
        let ids = Set(entries.filter { $0.kgCardId != nil }.map(\.notebookId))
        return ids.isEmpty ? ["default"] : ids.sorted()
    }

    static func notebookIDs(for filter: NotebookFilter, entries: [VocabularyEntry]) -> [String] {
        filter.isFiltered ? filter.selectedIds.sorted() : notebookIDs(from: entries)
    }

    /// Changes whenever any entry's local link state (add / hide / delete)
    /// changes, so the full graph can re-pull like the Stats thumbnail does.
    static func linksRevision(of entries: [VocabularyEntry]) -> Int {
        // Order-independent (wrapping sum of per-entry hashes): no string
        // building or sorting on the view-body hot path.
        var sum = 0
        for entry in entries {
            var hasher = Hasher()
            hasher.combine(entry.id)
            hasher.combine(entry.graphLinksJSON)
            sum = sum &+ hasher.finalize()
        }
        var hasher = Hasher()
        hasher.combine(entries.count)
        hasher.combine(sum)
        return hasher.finalize()
    }

    /// Hash of the actual request scope (notebooks pulled), so a filter change
    /// between multi-notebook sets re-triggers the link pull.
    static func requestKey(for filter: NotebookFilter, entries: [VocabularyEntry]) -> Int {
        var hasher = Hasher()
        hasher.combine(notebookIDs(for: filter, entries: entries))
        return hasher.finalize()
    }
}

struct KnowledgeGraphView: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.detailRouter) private var detailRouter
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore
    let allEntries: [VocabularyEntry]
    let notebookId: String?
    private let shouldLoadGraphData: Bool
    @State private var coordinator: KnowledgeGraphCoordinator

    init(allEntries: [VocabularyEntry], notebookId: String? = nil) {
        self.allEntries = allEntries
        self.notebookId = notebookId
        self.shouldLoadGraphData = true
        _coordinator = State(initialValue: KnowledgeGraphCoordinator())
    }

#if DEBUG
    init(
        allEntries: [VocabularyEntry],
        initialGraphLinks: [KGGraphLink],
        shouldLoadGraphData: Bool,
        notebookId: String? = nil
    ) {
        self.allEntries = allEntries
        self.notebookId = notebookId
        self.shouldLoadGraphData = shouldLoadGraphData
        _coordinator = State(initialValue: KnowledgeGraphCoordinator(links: initialGraphLinks))
    }
#endif

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
        .task(id: loadTrigger) {
            guard shouldLoadGraphData else { return }
            await loadGraphData()
        }
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

    /// Reload key: scope plus local link state, so edges refresh after the
    /// detail sheet hides / deletes / adds a link (#2538).
    private var loadTrigger: Int {
        var hasher = Hasher()
        hasher.combine(notebookId)
        hasher.combine(KnowledgeGraphNotebookScope.linksRevision(of: allEntries))
        return hasher.finalize()
    }

    private func loadGraphData() async {
        await coordinator.loadGraphData(
            authManager: authManager,
            kgService: kgService,
            notebookIDs: notebookId.map { [$0] }
                ?? KnowledgeGraphNotebookScope.notebookIDs(from: allEntries)
        )
    }

    /// Synchronous entry point for the error-state retry button — the only
    /// in-place way to re-run a failed `loadGraphData` without leaving the tab.
    /// `AppEmptyStateAction.handler` is sync, so the async load is bridged
    /// through a `Task`.
    private func reloadGraphData() {
        Task { await loadGraphData() }
    }
}
