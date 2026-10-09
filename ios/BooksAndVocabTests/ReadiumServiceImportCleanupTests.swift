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
    /// 以每次唯一的檔案內容辨識「這次匯入複製出的檔」，不比對整個共享目錄（其他測試可並行寫入）。
    @Test func corruptEPUBImportLeavesNoOrphanInBooksDirectory() async throws {
        let marker = Data("not a zip archive \(UUID().uuidString)".utf8)
        let source = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString + ".epub")
        try marker.write(to: source)
        defer { try? FileManager.default.removeItem(at: source) }

        await #expect(throws: (any Error).self) {
            _ = try await ReadiumService.shared.importEPUB(from: source)
        }
        let leaked = Self.epubFiles().filter { FileManager.default.contents(atPath: $0.path) == marker }
        #expect(leaked.isEmpty)
    }

    private static func epubFiles() -> [URL] {
        let urls = try? FileManager.default.contentsOfDirectory(
            at: Book.booksDirectory, includingPropertiesForKeys: nil)
        return (urls ?? []).filter { $0.pathExtension == "epub" }
    }
}
