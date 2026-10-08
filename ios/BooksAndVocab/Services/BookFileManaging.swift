import Foundation

/// 至少一個位置的書籍檔案刪除失敗（「檔案本來就不在」不算失敗）。
struct BookFileDeletionError: Error, LocalizedError {
    let fileName: String
    let failures: [(url: URL, error: Error)]

    var errorDescription: String? {
        let detail = failures
            .map { "\($0.url.path): \($0.error.localizedDescription)" }
            .joined(separator: "; ")
        return "book file removal failed (\(fileName)): \(detail)"
    }
}

protocol BookFileManaging: AnyObject {
    /// 刪除書籍檔案；任一位置刪除失敗會在**嘗試完所有位置後**拋出 `BookFileDeletionError`。
    /// 呼叫端必須處理失敗——吞掉會讓 row 已消失、檔案還在，下次 reconcile 書又復活。
    func deleteBookFile(named fileName: String) throws
}

final class LocalBookFileManager: BookFileManaging {
    /// nil = 每次刪除時才解析預設位置：iCloud 目錄可能啟動時不可用、之後才可用
    /// （`Book.iCloudBooksDirectory` 刻意不快取 nil），且解析可能阻塞，不可在 init 固化。
    private let fixedLocations: [URL]?

    init(locations: [URL]? = nil) {
        self.fixedLocations = locations
    }

    static func defaultLocations() -> [URL] {
        var urls: [URL] = []
        // 檔案可能在 iCloud 或本機（或兩者都有），同時清理
        if let iCloudDir = Book.iCloudBooksDirectory { urls.append(iCloudDir) }
        urls.append(Book.localBooksDirectory)
        // Legacy fallback: also check old EPUBs directory
        urls.append(
            FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("EPUBs")
        )
        return urls
    }

    func deleteBookFile(named fileName: String) throws {
        // 空檔名會讓 appendingPathComponent 指回目錄本身 → removeItem 會整個目錄刪掉
        guard !fileName.isEmpty else { return }

        let fm = FileManager.default
        var failures: [(url: URL, error: Error)] = []
        for location in fixedLocations ?? Self.defaultLocations() {
            let url = location.appendingPathComponent(fileName)
            do {
                try fm.removeItem(at: url)
            } catch where Self.isFileAbsent(error) {
                continue  // 只存在於其中一個位置是常態；已達成「不存在」
            } catch {
                AppLog.book.error("book file removal failed (\(url.path, privacy: .public)): \(error.localizedDescription)")
                failures.append((url, error))
            }
            Self.removeOriginals(forEpub: fileName, in: location, failures: &failures)
        }
        if !failures.isEmpty {
            throw BookFileDeletionError(fileName: fileName, failures: failures)
        }
    }

    /// TXT/MD 匯入時保留的原始檔副本名稱：由 EPUB 檔名（含 UUID，天然唯一）推導，
    /// 讓匯入與刪除共用同一規則，不依賴會撞名的來源檔名（#2440）。
    static func originalCopyName(forEpub fileName: String, sourceExt: String) -> String {
        let stem = (fileName as NSString).deletingPathExtension
        return "\(stem).\(sourceExt.lowercased())"
    }

    /// 刪除某位置下該書的 Originals 副本（txt / md）；不存在視為已達成。
    private static func removeOriginals(
        forEpub fileName: String,
        in location: URL,
        failures: inout [(url: URL, error: Error)]
    ) {
        let originals = location.appendingPathComponent("Originals", isDirectory: true)
        for ext in ["txt", "md"] {
            let url = originals.appendingPathComponent(originalCopyName(forEpub: fileName, sourceExt: ext))
            do {
                try FileManager.default.removeItem(at: url)
            } catch where isFileAbsent(error) {
                continue
            } catch {
                AppLog.book.error("book original removal failed (\(url.path, privacy: .public)): \(error.localizedDescription)")
                failures.append((url, error))
            }
        }
    }

    static func isFileAbsent(_ error: Error) -> Bool {
        let nsError = error as NSError
        if nsError.domain == NSCocoaErrorDomain,
           nsError.code == NSFileNoSuchFileError || nsError.code == NSFileReadNoSuchFileError {
            return true
        }
        if nsError.domain == NSPOSIXErrorDomain, nsError.code == Int(ENOENT) {
            return true
        }
        if let underlying = nsError.userInfo[NSUnderlyingErrorKey] as? Error {
            return isFileAbsent(underlying)
        }
        return false
    }
}
