import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct AppOrphanBookRecoveryTests {
    private func makeContainer() throws -> ModelContainer {
        let schema = Schema([
            Book.self,
            VocabularyEntry.self,
            ReviewRecord.self,
            Notebook.self,
            PodcastSeries.self,
            PodcastEpisode.self,
            PodcastProgress.self
        ])
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        return try ModelContainer(for: schema, configurations: [config])
    }

    @Test func recoversBooksFromLegacyEPUBsDirectory() throws {
        let container = try makeContainer()
        let fm = FileManager.default
        let legacyDir = fm.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("EPUBs")
        try fm.createDirectory(at: legacyDir, withIntermediateDirectories: true)

        let fileName = "\(UUID().uuidString)_Legacy Invisible Book.epub"
        let fileURL = legacyDir.appendingPathComponent(fileName)
        try Data("epub".utf8).write(to: fileURL)
        defer { try? fm.removeItem(at: fileURL) }

        AppOrphanBookRecovery.run(container: container, allowBareFileRecovery: true)

        let context = ModelContext(container)
        let recovered = try context.fetch(FetchDescriptor<Book>())
            .first { $0.epubFileName == fileName }

        #expect(recovered?.title == "Legacy Invisible Book")
        #expect(recovered?.format == .epub)
    }

    @Test func recoversEvictedPlaceholderUsingOriginalFileNameAndFormat() throws {
        let container = try makeContainer()
        let fm = FileManager.default
        let booksDir = Book.localBooksDirectory
        try fm.createDirectory(at: booksDir, withIntermediateDirectories: true)

        let fileName = "\(UUID().uuidString)_Cloud Missing PDF.pdf"
        let placeholderURL = booksDir.appendingPathComponent(".\(fileName).icloud")
        try Data("placeholder".utf8).write(to: placeholderURL)
        defer { try? fm.removeItem(at: placeholderURL) }

        AppOrphanBookRecovery.run(container: container, allowBareFileRecovery: true)

        let context = ModelContext(container)
        let recovered = try context.fetch(FetchDescriptor<Book>())
            .first { $0.epubFileName == fileName }

        #expect(recovered?.title == "Cloud Missing PDF")
        #expect(recovered?.format == .pdf)
    }
}
