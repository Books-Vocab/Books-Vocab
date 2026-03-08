import Foundation

protocol BookFileManaging: AnyObject {
    func deleteBookFile(named fileName: String)
}

final class LocalBookFileManager: BookFileManaging {
    func deleteBookFile(named fileName: String) {
        let url = Book.epubsDirectory.appendingPathComponent(fileName)
        try? FileManager.default.removeItem(at: url)
    }
}
