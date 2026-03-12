import Foundation

protocol BookFileManaging: AnyObject {
    func deleteBookFile(named fileName: String)
}

final class LocalBookFileManager: BookFileManaging {
    func deleteBookFile(named fileName: String) {
        let fm = FileManager.default
        // 檔案可能在 iCloud 或本機（或兩者都有），同時清理
        if let iCloudDir = Book.iCloudEpubsDirectory {
            try? fm.removeItem(at: iCloudDir.appendingPathComponent(fileName))
        }
        try? fm.removeItem(at: Book.localEpubsDirectory.appendingPathComponent(fileName))
    }
}
