#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

/// Pins `KnowledgeGraphPresentation.emptyState` — the pure-function seam that
/// decides which empty/error state the knowledge-graph scene shows.
///
/// The scene's only load entry point is `KnowledgeGraphView.task`, which fires
/// once on first appearance. If `loadGraphData` fails, `errorMessage` is set and
/// `emptyState` returns the error variant — without a retry affordance the user
/// is stranded and must leave the tab and return. This suite locks down that the
/// error branch carries an `AppEmptyStateAction` wired to a retry closure, while
/// the non-error branches (logged-out / loading / no-nodes) carry no action.
struct KnowledgeGraphPresentationTests {

    // MARK: - Graph node/edge consistency

    @Test func nodes_ignoreDanglingEndpoints_whenComputingDegree() {
        let source = Self.entry(word: "source", cardID: "source")
        let archivedTarget = Self.entry(word: "archived", cardID: "archived", archived: true)
        let links = [
            Self.link(id: "missing-target", from: "source", to: "missing"),
            Self.link(id: "archived-target", from: "source", to: "archived"),
        ]

        let nodes = KnowledgeGraphPresentation.nodes(
            from: [source, archivedTarget],
            links: links
        )
        let edges = KnowledgeGraphPresentation.edges(
            from: links,
            validNodeIDs: Set(nodes.map(\.id))
        )

        #expect(nodes.isEmpty, "dangling endpoints must not make a node appear linked")
        #expect(edges.isEmpty, "every rendered edge must have two rendered endpoints")
    }

    @Test func nodes_keepTwoSidedLinks_andIsolatedNodeToggle() {
        let linkedSource = Self.entry(word: "source", cardID: "source")
        let linkedTarget = Self.entry(word: "target", cardID: "target")
        let isolated = Self.entry(word: "isolated", cardID: "isolated")
        let links = [Self.link(id: "source-target", from: "source", to: "target")]

        let linkedNodes = KnowledgeGraphPresentation.nodes(
            from: [linkedSource, linkedTarget, isolated],
            links: links
        )
        let allNodes = KnowledgeGraphPresentation.nodes(
            from: [linkedSource, linkedTarget, isolated],
            links: links,
            showIsolatedNodes: true
        )

        #expect(linkedNodes.map(\.id) == ["source", "target"])
        #expect(linkedNodes.allSatisfy { $0.degree == 1 })
        #expect(allNodes.map(\.id) == ["source", "target", "isolated"])
        #expect(allNodes.first { $0.id == "isolated" }?.degree == 0)
        #expect(
            KnowledgeGraphPresentation.edges(
                from: links,
                validNodeIDs: Set(linkedNodes.map(\.id))
            ).count == 1
        )
    }

    // MARK: - Notebook-scoped graph loading

    @Test func graphNotebookScope_selectsOnlySingleNotebook() {
        #expect(
            KnowledgeGraphNotebookScope.notebookID(
                for: NotebookFilter(selectedIds: ["nb-1"])
            ) == "nb-1"
        )
        #expect(
            KnowledgeGraphNotebookScope.notebookID(
                for: NotebookFilter(selectedIds: [])
            ) == nil
        )
        #expect(
            KnowledgeGraphNotebookScope.notebookID(
                for: NotebookFilter(selectedIds: ["nb-1", "nb-2"])
            ) == nil
        )
    }

    @Test func graphNotebookScope_fromEntries_returnsSortedDistinctSyncedNotebooks() {
        let a = Self.entry(word: "a", cardID: "a", notebookID: "nb-b")
        let b = Self.entry(word: "b", cardID: "b", notebookID: "nb-a")
        let c = Self.entry(word: "c", cardID: "c", notebookID: "nb-b")
        let unsynced = Self.entry(word: "d", cardID: "d", notebookID: "nb-z")
        unsynced.kgCardId = nil

        #expect(KnowledgeGraphNotebookScope.notebookIDs(from: [a, b, c, unsynced]) == ["nb-a", "nb-b"])
        #expect(KnowledgeGraphNotebookScope.notebookIDs(from: []) == ["default"])
    }

    @Test func graphNotebookScope_forFilter_usesSelectionElseEntries() {
        let a = Self.entry(word: "a", cardID: "a", notebookID: "nb-a")
        let b = Self.entry(word: "b", cardID: "b", notebookID: "nb-b")

        #expect(
            KnowledgeGraphNotebookScope.notebookIDs(
                for: NotebookFilter(selectedIds: ["nb-2", "nb-1"]), entries: [a, b]
            ) == ["nb-1", "nb-2"]
        )
        #expect(
            KnowledgeGraphNotebookScope.notebookIDs(for: NotebookFilter(selectedIds: []), entries: [a, b])
                == ["nb-a", "nb-b"]
        )
    }

    @Test func pullGraphLinks_fansOutAcrossNotebooks_andDedupes() async throws {
        let service = RecordingGraphService(linksByNotebook: [
            "nb-a": [Self.link(id: "l1", from: "a1", to: "a2")],
            "nb-b": [Self.link(id: "l1", from: "a1", to: "a2"), Self.link(id: "l2", from: "b1", to: "b2")],
        ])
        let links = try await service.pullGraphLinks(notebookIDs: ["nb-a", "nb-b"])
        #expect(links.map(\.id) == ["l1", "l2"])
        #expect(service.requested == ["nb-a", "nb-b"])
        #expect(service.defaultPullCount == 0, "multi-notebook scope must never fall back to the default notebook")
    }

    @Test func pullGraphLinks_skipsForbiddenNotebook_butPropagatesOtherErrors() async throws {
        let service = RecordingGraphService(
            linksByNotebook: ["nb-b": [Self.link(id: "l2", from: "b1", to: "b2")]],
            errorsByNotebook: ["nb-gone": KGError.httpError(statusCode: 403, detail: "gone")]
        )
        let links = try await service.pullGraphLinks(notebookIDs: ["nb-gone", "nb-b"])
        #expect(links.map(\.id) == ["l2"])

        let failing = RecordingGraphService(
            linksByNotebook: [:],
            errorsByNotebook: ["nb-x": KGError.httpError(statusCode: 500, detail: "boom")]
        )
        await #expect(throws: KGError.self) {
            _ = try await failing.pullGraphLinks(notebookIDs: ["nb-x"])
        }
        let offline = RecordingGraphService(linksByNotebook: [:], errorsByNotebook: ["nb-x": KGError.offline])
        await #expect(throws: KGError.self) {
            _ = try await offline.pullGraphLinks(notebookIDs: ["nb-x"])
        }
    }

    @Test func pullGraphLinks_emptyIDs_makesNoRequest() async throws {
        let service = RecordingGraphService(linksByNotebook: [:])
        let links = try await service.pullGraphLinks(notebookIDs: [])
        #expect(links.isEmpty)
        #expect(service.requested.isEmpty)
        #expect(service.defaultPullCount == 0)
    }

    @Test func nonDefaultNotebookNodes_getDegreeFromFanOutLinks() async throws {
        let b1 = Self.entry(word: "b1", cardID: "b1", notebookID: "nb-b")
        let b2 = Self.entry(word: "b2", cardID: "b2", notebookID: "nb-b")
        let service = RecordingGraphService(linksByNotebook: [
            "nb-a": [],
            "nb-b": [Self.link(id: "l", from: "b1", to: "b2")],
        ])
        let a1 = Self.entry(word: "a1", cardID: "a1", notebookID: "nb-a")
        let entries = [a1, b1, b2]
        let links = try await service.pullGraphLinks(
            notebookIDs: KnowledgeGraphNotebookScope.notebookIDs(from: entries)
        )
        let nodes = KnowledgeGraphPresentation.nodes(from: entries, links: links)
        #expect(nodes.map(\.id) == ["b1", "b2"])
        #expect(nodes.allSatisfy { $0.degree == 1 })
    }

    @MainActor
    @Test func graphLinksRevision_changesWhenEntryLinkStateChanges() {
        let e = Self.entry(word: "a", cardID: "a")
        let before = KnowledgeGraphNotebookScope.linksRevision(of: [e])
        e.graphLinksJSON = "[{\"changed\":true}]"
        #expect(KnowledgeGraphNotebookScope.linksRevision(of: [e]) != before)
    }

    @MainActor
    @Test func graphRequestKey_differsAcrossFilterScopes() {
        let a = Self.entry(word: "a", cardID: "a", notebookID: "A")
        let b = Self.entry(word: "b", cardID: "b", notebookID: "B")
        let c = Self.entry(word: "c", cardID: "c", notebookID: "C")
        let all = [a, b, c]
        let key = { (ids: Set<String>) in
            KnowledgeGraphNotebookScope.requestKey(for: NotebookFilter(selectedIds: ids), entries: all)
        }
        #expect(key(["A", "B"]) != key(["A", "C"]))
        #expect(key(["A", "B"]) != key([]))
        #expect(key(["A", "B"]) == key(["B", "A"]))
    }

    @Test func pullGraphLinks_singleNotebook_issuesExactlyOneRequest() async throws {
        let service = RecordingGraphService(linksByNotebook: ["x": [Self.link(id: "l", from: "a", to: "b")]])
        let links = try await service.pullGraphLinks(notebookIDs: ["x"])
        #expect(links.map(\.id) == ["l"])
        #expect(service.requested == ["x"])
        #expect(service.defaultPullCount == 0)
    }

    @MainActor
    @Test func graphLinksRevision_isOrderIndependent() {
        let a = Self.entry(word: "a", cardID: "a")
        let b = Self.entry(word: "b", cardID: "b")
        #expect(KnowledgeGraphNotebookScope.linksRevision(of: [a, b]) == KnowledgeGraphNotebookScope.linksRevision(of: [b, a]))
    }

    // MARK: - Error branch carries a retry action

    @Test func errorState_includesRetryAction() {
        let state = KnowledgeGraphPresentation.emptyState(
            isLoggedIn: true,
            isLoading: false,
            errorMessage: "網路連線中斷",
            nodes: [],
            onRetry: {}
        )
        #expect(state != nil, "an error must still surface an empty-state card")
        #expect(state?.action != nil, "the error state must offer a retry action so the user is not stranded")
        #expect(state?.description == "網路連線中斷", "the error description must surface the underlying message")
    }

    @Test func errorState_retryActionInvokesProvidedClosure() {
        var retryCount = 0
        let state = KnowledgeGraphPresentation.emptyState(
            isLoggedIn: true,
            isLoading: false,
            errorMessage: "逾時",
            nodes: [],
            onRetry: { retryCount += 1 }
        )
        state?.action?.handler()
        #expect(retryCount == 1, "triggering the empty-state action must re-run the load closure")
    }

    @Test func errorState_withoutRetryClosure_hasNoAction() throws {
        // When no retry closure is supplied the error card degrades gracefully
        // to a plain message rather than a dead button.
        let state = try #require(KnowledgeGraphPresentation.emptyState(
            isLoggedIn: true,
            isLoading: false,
            errorMessage: "失敗",
            nodes: [],
            onRetry: nil
        ))
        #expect(state.action == nil)
    }

    // MARK: - Non-error branches carry no retry action

    @Test func loggedOutState_hasNoRetryAction() throws {
        let state = try #require(KnowledgeGraphPresentation.emptyState(
            isLoggedIn: false,
            isLoading: false,
            errorMessage: nil,
            nodes: [],
            onRetry: {}
        ))
        #expect(state.action == nil, "the logged-out prompt is not a retryable failure")
    }

    @Test func loadingState_hasNoRetryAction() throws {
        let state = try #require(KnowledgeGraphPresentation.emptyState(
            isLoggedIn: true,
            isLoading: true,
            errorMessage: nil,
            nodes: [],
            onRetry: {}
        ))
        #expect(state.action == nil, "a load in progress must not show a retry button")
    }

    @Test func emptyGraphState_hasNoRetryAction() {
        // No error, no nodes — the graph is genuinely empty, not failed.
        let state = KnowledgeGraphPresentation.emptyState(
            isLoggedIn: true,
            isLoading: false,
            errorMessage: nil,
            nodes: [],
            syncedEntryCount: 0,
            onRetry: {}
        )
        #expect(state != nil)
        #expect(state?.action == nil, "an empty (non-failed) graph offers no retry")
    }

    @Test func populatedGraph_producesNoEmptyState() {
        let node = KnowledgeGraphNode(
            id: "1", word: "subtle", tier: "gradient", colorHex: nil, ratio: 0.2, degree: 1
        )
        let state = KnowledgeGraphPresentation.emptyState(
            isLoggedIn: true,
            isLoading: false,
            errorMessage: nil,
            nodes: [node],
            onRetry: {}
        )
        #expect(state == nil, "a graph with nodes resolves to `.content`, no empty state")
    }

    private static func entry(
        word: String,
        cardID: String,
        archived: Bool = false,
        notebookID: String = "default"
    ) -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: word,
            translation: word,
            context: "",
            bookTitle: "Book"
        )
        entry.syncStatus = VocabularySyncState.synced.rawValue
        entry.kgCardId = cardID
        entry.notebookId = notebookID
        entry.isArchived = archived
        return entry
    }

    private static func link(id: String, from: String, to: String) -> KGGraphLink {
        KGGraphLink(
            id: id,
            fromId: from,
            toId: to,
            kind: "shares_usage",
            confidence: 1,
            reason: "test"
        )
    }
}
private final class RecordingGraphService: GraphServing {
    let linksByNotebook: [String: [KGGraphLink]]
    let errorsByNotebook: [String: Error]
    private(set) var requested: [String] = []
    private(set) var defaultPullCount = 0

    init(linksByNotebook: [String: [KGGraphLink]], errorsByNotebook: [String: Error] = [:]) {
        self.linksByNotebook = linksByNotebook
        self.errorsByNotebook = errorsByNotebook
    }

    func pullGraphLinks() async throws -> [KGGraphLink] {
        defaultPullCount += 1
        return []
    }

    func pullGraphLinks(notebookId: String) async throws -> [KGGraphLink] {
        requested.append(notebookId)
        if let error = errorsByNotebook[notebookId] { throw error }
        return linksByNotebook[notebookId] ?? []
    }

    func createManualLink(fromId: String, toId: String, notebookId: String) async throws -> KGGraphLink {
        throw KGError.offline
    }
    func deleteLink(linkId: String, notebookId: String) async throws {}
    func hideLink(linkId: String, notebookId: String) async throws {}
    func unhideLink(linkId: String, notebookId: String) async throws {}
}
#endif
