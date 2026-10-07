import Foundation
import Testing
@testable import BooksAndVocab

/// #2040：複習卡的單字本標示——何時畫（單本 vs 多本入口）與名稱解析／備援。
struct ReviewCardNotebookBadgeTests {
    private func notebook(
        _ remoteId: String,
        name: String,
        color: String? = nil,
        isDefault: Bool = false,
        deleted: Bool = false
    ) -> Notebook {
        let notebook = Notebook(remoteId: remoteId, name: name, color: color, isDefault: isDefault)
        notebook.isSoftDeleted = deleted
        return notebook
    }

    // MARK: When to show

    @Test func single_notebook_session_draws_no_badge() {
        let badges = ReviewCardNotebookBadgeResolver.badges(
            sessionNotebookIDs: ["nb-a", "nb-a", "nb-a"],
            notebooks: [notebook("nb-a", name: "Alpha"), notebook("nb-b", name: "Beta")]
        )
        #expect(badges.isEmpty)
    }

    @Test func empty_session_draws_no_badge() {
        #expect(ReviewCardNotebookBadgeResolver.badges(sessionNotebookIDs: [], notebooks: []).isEmpty)
        #expect(!ReviewCardNotebookBadgeResolver.spansMultipleNotebooks([String]()))
    }

    @Test func multi_notebook_session_labels_every_session_notebook() {
        let badges = ReviewCardNotebookBadgeResolver.badges(
            sessionNotebookIDs: ["nb-a", "nb-b", "nb-a"],
            notebooks: [
                notebook("nb-a", name: "Alpha", color: "#B1C5AE"),
                notebook("nb-b", name: "Beta"),
                notebook("nb-c", name: "Gamma")
            ]
        )
        #expect(Set(badges.keys) == ["nb-a", "nb-b"])
        #expect(badges["nb-a"] == ReviewCardNotebookBadge(notebookId: "nb-a", name: "Alpha", colorHex: "#B1C5AE"))
        #expect(badges["nb-b"] == ReviewCardNotebookBadge(notebookId: "nb-b", name: "Beta", colorHex: nil))
    }

    // MARK: Name resolution / fallback

    @Test func unknown_notebook_falls_back_to_localized_name_never_the_id() {
        let badge = ReviewCardNotebookBadgeResolver.badge(for: "nb-unsynced-42", notebooks: [])
        #expect(badge.name == L10n.string("todayReview.card.notebook.unnamed"))
        #expect(!badge.name.contains("nb-unsynced-42"))
        #expect(badge.name != "todayReview.card.notebook.unnamed", "fallback key must be localized")
        #expect(badge.colorHex == nil)
    }

    @Test func soft_deleted_notebook_is_not_used_for_the_name() {
        let badge = ReviewCardNotebookBadgeResolver.badge(
            for: "nb-a",
            notebooks: [notebook("nb-a", name: "Deleted Alpha", color: "#DCABA4", deleted: true)]
        )
        #expect(badge.name == L10n.string("todayReview.card.notebook.unnamed"))
        #expect(badge.colorHex == nil)
    }

    @Test func blank_name_falls_back_instead_of_rendering_empty() {
        let badge = ReviewCardNotebookBadgeResolver.badge(for: "nb-a", notebooks: [notebook("nb-a", name: "   ")])
        #expect(badge.name == L10n.string("todayReview.card.notebook.unnamed"))
    }

    @Test func default_sentinel_resolves_to_the_default_notebook() {
        let badge = ReviewCardNotebookBadgeResolver.badge(
            for: "default",
            notebooks: [notebook("srv-123", name: "My Words", color: "#AFC2D3", isDefault: true)]
        )
        #expect(badge.name == "My Words")
        #expect(badge.colorHex == "#AFC2D3")
    }

    @Test func default_sentinel_without_a_row_uses_the_default_fallback_name() {
        let badge = ReviewCardNotebookBadgeResolver.badge(for: "default", notebooks: [])
        #expect(badge.name == L10n.string("todayReview.card.notebook.default"))
        #expect(badge.name != "default")
        #expect(badge.name != "todayReview.card.notebook.default", "fallback key must be localized")
    }

    @Test func notebook_name_is_trimmed() {
        let badge = ReviewCardNotebookBadgeResolver.badge(for: "nb-a", notebooks: [notebook("nb-a", name: "  Alpha \n")])
        #expect(badge.name == "Alpha")
    }
}
