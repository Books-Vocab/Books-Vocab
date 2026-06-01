import Testing
@testable import BooksBrowser

struct NotebookSelectionPolicyTests {
    @Test func changingNotebookDismissesStaleDetail() {
        #expect(NotebookSelectionPolicy.shouldDismissDetail(currentNotebookId: nil, nextNotebookId: "default"))
        #expect(NotebookSelectionPolicy.shouldDismissDetail(currentNotebookId: "a", nextNotebookId: "b"))
        #expect(!NotebookSelectionPolicy.shouldDismissDetail(currentNotebookId: "a", nextNotebookId: "a"))
    }
}
