#if DEBUG
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

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

    @Test
    func failedICloudRetryControlSitsOutsideBookNavigationLabel() throws {
        let sourceRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
        let bookshelfSource = try String(
            contentsOf: sourceRoot.appendingPathComponent(
                "BooksAndVocab/Views/Bookshelf/BookshelfView.swift"
            ),
            encoding: .utf8
        )
        let bookCardSource = try String(
            contentsOf: sourceRoot.appendingPathComponent(
                "BooksAndVocab/Views/Bookshelf/Components/BookCard.swift"
            ),
            encoding: .utf8
        )

        let navigationStart = try #require(
            bookshelfSource.range(of: "NavigationLink(value: book) {")
        )
        let navigationEnd = try #require(
            bookshelfSource.range(
                of: ".buttonStyle(.bookshelfCard)",
                range: navigationStart.upperBound..<bookshelfSource.endIndex
            )
        )
        let navigationLabel = String(
            bookshelfSource[navigationStart.upperBound..<navigationEnd.lowerBound]
        )

        #expect(
            bookshelfSource.contains("BookCardRetryButton(fileName: book.epubFileName)"),
            "Bookshelf must render the retry control outside the NavigationLink label"
        )
        #expect(
            !navigationLabel.contains("BookCardRetryButton"),
            "NavigationLink labels must not contain the interactive retry control"
        )
        #expect(
            bookCardSource.contains("case .failed:\n                EmptyView()"),
            "BookCard must keep the failed state non-interactive inside the link label"
        )
    }

#if os(iOS)
    @MainActor
    private final class UncalledImportService: BookshelfImporting {
        private func draft() -> ImportedBookDraft {
            ImportedBookDraft(
                title: "unused",
                author: "unused",
                coverImageData: nil,
                fileName: "unused.epub",
                format: .epub
            )
        }

        func importBook(
            from _: URL,
            progress _: (@Sendable (Double) -> Void)?
        ) async throws -> ImportedBookDraft {
            draft()
        }

        func importTXT(
            from _: URL,
            progress _: (@Sendable (Double) -> Void)?
        ) async throws -> ImportedBookDraft {
            draft()
        }

        func importMD(
            from _: URL,
            progress _: (@Sendable (Double) -> Void)?
        ) async throws -> ImportedBookDraft {
            draft()
        }

        func importPDF(
            from _: URL,
            progress _: (@Sendable (Double) -> Void)?
        ) async throws -> ImportedBookDraft {
            draft()
        }
    }

    @Test
    @MainActor
    func cancelledFileImporterDoesNotPresentImportError() throws {
        let configuration = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        let container = try ModelContainer(for: Book.self, configurations: configuration)
        let coordinator = BookshelfCoordinator()
        let toast = AppToastCoordinator()

        coordinator.handleFileImport(
            .failure(CocoaError(.userCancelled)),
            modelContext: container.mainContext,
            importService: UncalledImportService(),
            toastCoordinator: toast
        )

        #expect(coordinator.errorMessage == nil)
        #expect(coordinator.errorDiagnosis == nil)
        #expect(!coordinator.showError)
        #expect(toast.current == nil)
    }
#endif
}
#endif
