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

    @Test func errorState_withoutRetryClosure_hasNoAction() {
        // When no retry closure is supplied the error card degrades gracefully
        // to a plain message rather than a dead button.
        let state = KnowledgeGraphPresentation.emptyState(
            isLoggedIn: true,
            isLoading: false,
            errorMessage: "失敗",
            nodes: [],
            onRetry: nil
        )
        #expect(state?.action == nil)
    }

    // MARK: - Non-error branches carry no retry action

    @Test func loggedOutState_hasNoRetryAction() {
        let state = KnowledgeGraphPresentation.emptyState(
            isLoggedIn: false,
            isLoading: false,
            errorMessage: nil,
            nodes: [],
            onRetry: {}
        )
        #expect(state?.action == nil, "the logged-out prompt is not a retryable failure")
    }

    @Test func loadingState_hasNoRetryAction() {
        let state = KnowledgeGraphPresentation.emptyState(
            isLoggedIn: true,
            isLoading: true,
            errorMessage: nil,
            nodes: [],
            onRetry: {}
        )
        #expect(state?.action == nil, "a load in progress must not show a retry button")
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
}
#endif
