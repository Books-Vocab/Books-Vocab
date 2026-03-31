import Foundation

protocol BookFileManaging: AnyObject {
    func deleteBookFile(named fileName: String)
}

final class LocalBookFileManager: BookFileManaging {
    func deleteBookFile(named fileName: String) {
        let fm = FileManager.default
        // 檔案可能在 iCloud 或本機（或兩者都有），同時清理
        if let iCloudDir = Book.iCloudBooksDirectory {
            try? fm.removeItem(at: iCloudDir.appendingPathComponent(fileName))
        }
        try? fm.removeItem(at: Book.localBooksDirectory.appendingPathComponent(fileName))

        // Clean up original file if it exists
        let originalsDir = Book.booksDirectory.appendingPathComponent("Originals")
        let origFile = originalsDir.appendingPathComponent(fileName)
        try? fm.removeItem(at: origFile)
    }
}
