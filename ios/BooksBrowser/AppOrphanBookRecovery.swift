//
//  AppOrphanBookRecovery.swift
//  BooksBrowser
//
//  Store reset 後掃描磁碟與 DB 對齊 — 為磁碟上有檔但 DB 沒記錄的書補建 Book。
//  與 AppBootstrap 解耦：bootstrap 關心「拿到 container」，本檔關心「磁碟 vs DB 對齊」。
//

import Foundation
import SwiftData
import os

enum AppOrphanBookRecovery {
    @MainActor
    static func run(container: ModelContainer) {
        let context = ModelContext(container)
        let fm = FileManager.default
        let supportedExtensions: Set<String> = ["epub", "txt", "md", "pdf"]

        // Scan both local and iCloud directories
        var allFiles: [URL] = []
        if let files = try? fm.contentsOfDirectory(at: Book.localBooksDirectory, includingPropertiesForKeys: nil) {
            allFiles.append(contentsOf: files.filter { supportedExtensions.contains($0.pathExtension.lowercased()) })
        }
        if let iCloudDir = Book.iCloudBooksDirectory,
           let files = try? fm.contentsOfDirectory(at: iCloudDir, includingPropertiesForKeys: nil) {
            allFiles.append(contentsOf: files.filter { supportedExtensions.contains($0.pathExtension.lowercased()) })
        }

        AppLog.app.info("recoverOrphanBooks: local=\(Book.localBooksDirectory.path), iCloud=\(Book.iCloudBooksDirectory?.path ?? "nil"), found \(allFiles.count) book file(s)")
        guard !allFiles.isEmpty else {
            AppLog.app.info("recoverOrphanBooks: no book files found on disk")
            return
        }

        let existing: Set<String>
        if let books = try? context.fetch(FetchDescriptor<Book>()) {
            existing = Set(books.map(\.epubFileName))
        } else {
            existing = []
        }

        var recovered = 0
        for file in allFiles {
            let fileName = file.lastPathComponent
            guard !existing.contains(fileName) else { continue }

            // Skip .icloud placeholder files and Originals directory
            guard !fileName.hasPrefix("."), fileName != "Originals" else { continue }

            let ext = file.pathExtension.lowercased()
            let format: BookFormat = switch ext {
            case "epub": .epub
            case "txt":  .txt
            case "md":   .md
            case "pdf":  .pdf
            default: .epub
            }

            // Derive title from fileName (strip UUID prefix if present)
            let baseName = file.deletingPathExtension().lastPathComponent
            let title = baseName.count > 37 && baseName.dropFirst(36).first == "_"
                ? String(baseName.dropFirst(37))  // UUID_originalName pattern
                : baseName

            let book = Book(title: title, author: "", fileName: fileName, format: format)
            context.insert(book)
            recovered += 1
        }

        if recovered > 0 {
            do {
                try context.save()
                AppLog.app.info("Recovered \(recovered) orphan book(s) from disk")
            } catch {
                AppLog.app.error("recoverOrphanBooks: save failed, \(recovered) book(s) not persisted: \(error.localizedDescription)")
            }
        }
    }
}
