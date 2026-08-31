#if DEBUG
import Foundation
import Testing

@Suite
struct BookshelfNavigationContractTests {
    @Test
    func bookshelfKeepsNavigationRootStableAcrossLibraryStateChanges() throws {
        let sourceURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Views/Bookshelf/BookshelfView.swift")
        let source = try String(contentsOf: sourceURL, encoding: .utf8)

        let navigationStack = try #require(
            source.range(of: "NavigationStack(path: $navigationPath)")
        )
        let rootBoundary = try #require(
            source.range(
                of: ".safeAreaInset(edge: .top",
                range: navigationStack.upperBound..<source.endIndex
            )
        )
        let navigationRoot = String(source[navigationStack.upperBound..<rootBoundary.lowerBound])

        #expect(
            navigationRoot.contains("BookshelfRootContent("),
            "Bookshelf navigation root must delegate state presentation to a stable wrapper"
        )
        #expect(
            !navigationRoot.contains("if books.isEmpty"),
            "Bookshelf must not replace the NavigationStack root subtree on library state changes"
        )
    }
}
#endif
