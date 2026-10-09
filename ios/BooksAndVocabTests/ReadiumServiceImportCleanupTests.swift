//
//  ReadiumServiceImportCleanupTests.swift
//  Books & Vocab Tests
//

import Foundation
import Testing
@testable import BooksAndVocab

@MainActor
struct ReadiumServiceImportCleanupTests {

    /// 壞檔 EPUB 開啟失敗時，已複製進 Books 目錄的孤檔必須被清掉（#2534）。
    @Test func corruptEPUBImportLeavesNoOrphanInBooksDirectory() async throws {
        let source = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString + ".epub")
        try Data("not a zip archive".utf8).write(to: source)
        defer { try? FileManager.default.removeItem(at: source) }

        let before = Self.listing()
        await #expect(throws: (any Error).self) {
            _ = try await ReadiumService.shared.importEPUB(from: source)
        }
        #expect(Self.listing() == before)
    }

    private static func listing() -> Set<String> {
        let names = try? FileManager.default.contentsOfDirectory(atPath: Book.booksDirectory.path)
        return Set(names ?? [])
    }
}
