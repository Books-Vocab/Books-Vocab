//
//  BookMetadataRepairServiceNeedsRepairTests.swift
//  Books & Vocab Tests
//
//  Pins BookMetadataRepairService.needsRepair() — the gate that decides which
//  books enter the expensive EPUB re-parse path. A false-positive means
//  unnecessary IO every launch; a false-negative means a corrupted book stays
//  broken.
//

import Foundation
import Testing
@testable import BooksAndVocab

@MainActor
struct BookMetadataRepairServiceNeedsRepairTests {

    /// Fake extractor — needsRepair never calls it, but the init requires one.
    private struct FakeExtractor: BookMetadataExtracting {
        func extractMetadata(fromEPUBAt url: URL) async throws -> ExtractedBookMetadata {
            ExtractedBookMetadata(title: "", author: "", coverImageData: nil)
        }
    }

    private func makeService(
        defaults: UserDefaults = UserDefaults(suiteName: #file)!,
        fileURL: URL? = nil
    ) -> BookMetadataRepairService {
        BookMetadataRepairService(
            extractor: FakeExtractor(),
            fileManager: .default,
            userDefaults: defaults,
            fileURLProvider: { _ in fileURL ?? URL(fileURLWithPath: "/dev/null") }
        )
    }

    private func makeBook(
        title: String,
        author: String = "Author",
        fileName: String = "book.epub",
        format: BookFormat = .epub
    ) -> Book {
        let book = Book(title: title, author: author, fileName: fileName, format: format)
        return book
    }

    // MARK: - positive cases

    @Test func fallbackTitleNeedsRepair() throws {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".epub")
        FileManager.default.createFile(atPath: tmp.path, contents: Data())
        defer { try? FileManager.default.removeItem(at: tmp) }

        let service = makeService(fileURL: tmp)
        let book = makeBook(title: "book")   // title == fileName base → fallback
        #expect(service.needsRepair(book) == true)
    }

    @Test func fallbackAuthorNeedsRepair() throws {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".epub")
        FileManager.default.createFile(atPath: tmp.path, contents: Data())
        defer { try? FileManager.default.removeItem(at: tmp) }

        let service = makeService(fileURL: tmp)
        let book = makeBook(title: "Real Title", author: "")   // empty author → fallback
        #expect(service.needsRepair(book) == true)
    }

    // MARK: - negative cases

    @Test func cleanMetadataDoesNotNeedRepair() throws {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".epub")
        FileManager.default.createFile(atPath: tmp.path, contents: Data())
        defer { try? FileManager.default.removeItem(at: tmp) }

        let service = makeService(fileURL: tmp)
        let book = makeBook(title: "Pride and Prejudice", author: "Jane Austen")
        #expect(service.needsRepair(book) == false)
    }

    @Test func nonEpubFormatDoesNotNeedRepair() throws {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".pdf")
        FileManager.default.createFile(atPath: tmp.path, contents: Data())
        defer { try? FileManager.default.removeItem(at: tmp) }

        let service = makeService(fileURL: tmp)
        let book = makeBook(title: "book", fileName: "book.pdf", format: .pdf)
        #expect(service.needsRepair(book) == false)
    }

    @Test func unreadableFileDoesNotNeedRepair() {
        let service = makeService(fileURL: URL(fileURLWithPath: "/nonexistent/book.epub"))
        let book = makeBook(title: "book")
        #expect(service.needsRepair(book) == false)
    }

    @Test func skippedFileDoesNotNeedRepair() throws {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".epub")
        FileManager.default.createFile(atPath: tmp.path, contents: Data())
        defer { try? FileManager.default.removeItem(at: tmp) }

        let defaults = UserDefaults(suiteName: #file)!
        let key = "kg_metadata_repair_skip_v1"
        defaults.set([tmp.lastPathComponent], forKey: key)
        defer { defaults.removeObject(forKey: key) }

        let service = makeService(defaults: defaults, fileURL: tmp)
        let book = makeBook(title: "book", fileName: tmp.lastPathComponent)
        #expect(service.needsRepair(book) == false)
    }
}
