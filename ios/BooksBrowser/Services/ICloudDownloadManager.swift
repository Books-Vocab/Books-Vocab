//
//  ICloudDownloadManager.swift
//  BooksBrowser
//

import Foundation

/// iCloud 檔案下載狀態
enum ICloudFileState: Equatable {
    /// 已下載，本機可用
    case current
    /// 下載中，進度 0.0–1.0
    case downloading(Double)
    /// 未下載，等待觸發
    case notDownloaded
}

/// 使用 NSMetadataQuery 監控 iCloud ubiquity container 中的 EPUB 下載狀態，
/// 自動觸發待下載檔案並追蹤即時進度。
@MainActor
@Observable
final class ICloudDownloadManager {
    private(set) var fileStates: [String: ICloudFileState] = [:]
    /// 查詢是否已完成首次 gather（用於 UI 區分「尚未查詢」與「查詢後無結果」）
    private(set) var hasGathered = false

    private var metadataQuery: NSMetadataQuery?
    private var gatherObserver: Any?
    private var updateObserver: Any?
    private var triggeredFiles: Set<String> = []

    /// 取得特定檔案的下載狀態（nil = 查詢尚未追蹤到此檔案）
    func state(for fileName: String) -> ICloudFileState? {
        fileStates[fileName]
    }

    /// 開始監控 iCloud EPUB 檔案
    func startMonitoring() {
        guard metadataQuery == nil else { return }

        // 診斷：檢查 iCloud 身分與容器
        let fm = FileManager.default
        let token = fm.ubiquityIdentityToken
        AppLog.book.info("iCloud identity token: \(token != nil ? "present" : "nil")")

        guard let containerURL = fm.url(forUbiquityContainerIdentifier: nil) else {
            AppLog.book.error("ICloudDownloadManager: ubiquity container URL is nil — iCloud not available")
            return
        }
        AppLog.book.info("ICloudDownloadManager: container = \(containerURL.path)")

        let epubsDir = containerURL.appendingPathComponent("Documents/EPUBs")
        // 列出目錄中已知的檔案（含 .icloud placeholder）
        if let contents = try? fm.contentsOfDirectory(atPath: epubsDir.path) {
            AppLog.book.info("ICloudDownloadManager: EPUBs directory has \(contents.count) entries: \(contents.joined(separator: ", "))")
        } else {
            AppLog.book.info("ICloudDownloadManager: EPUBs directory is empty or not accessible")
        }

        let query = NSMetadataQuery()
        query.searchScopes = [NSMetadataQueryUbiquitousDocumentsScope]
        query.predicate = NSPredicate(format: "%K LIKE '*.epub'", NSMetadataItemFSNameKey)

        gatherObserver = NotificationCenter.default.addObserver(
            forName: .NSMetadataQueryDidFinishGathering,
            object: query,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.hasGathered = true
                self?.processQueryResults(isGather: true)
            }
        }

        updateObserver = NotificationCenter.default.addObserver(
            forName: .NSMetadataQueryDidUpdate,
            object: query,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.processQueryResults(isGather: false) }
        }

        query.start()
        metadataQuery = query
        AppLog.book.info("ICloudDownloadManager: monitoring started")
    }

    /// 停止監控
    func stopMonitoring() {
        metadataQuery?.stop()
        metadataQuery = nil
        if let o = gatherObserver { NotificationCenter.default.removeObserver(o) }
        if let o = updateObserver { NotificationCenter.default.removeObserver(o) }
        gatherObserver = nil
        updateObserver = nil
    }

    /// 手動觸發特定檔案下載
    func triggerDownload(for fileName: String) {
        guard let dir = Book.iCloudBooksDirectory else { return }
        let url = dir.appendingPathComponent(fileName)
        do {
            try FileManager.default.startDownloadingUbiquitousItem(at: url)
            if fileStates[fileName] == nil || fileStates[fileName] == .notDownloaded {
                fileStates[fileName] = .downloading(0)
            }
            AppLog.book.info("ICloudDownloadManager: download triggered — \(fileName)")
        } catch {
            AppLog.book.error("ICloudDownloadManager: trigger failed — \(fileName): \(error.localizedDescription)")
        }
    }

    // MARK: - Private

    private func processQueryResults(isGather: Bool) {
        guard let query = metadataQuery else { return }
        query.disableUpdates()
        defer { query.enableUpdates() }

        if isGather {
            AppLog.book.info("ICloudDownloadManager: query gathered \(query.resultCount) epub file(s)")
        }

        for i in 0..<query.resultCount {
            guard let item = query.result(at: i) as? NSMetadataItem,
                  let fileName = item.value(forAttribute: NSMetadataItemFSNameKey) as? String
            else { continue }

            let status = item.value(
                forAttribute: NSMetadataUbiquitousItemDownloadingStatusKey
            ) as? String
            let percent = item.value(
                forAttribute: NSMetadataUbiquitousItemPercentDownloadedKey
            ) as? Double
            let isUploading = item.value(
                forAttribute: NSMetadataUbiquitousItemIsUploadingKey
            ) as? Bool ?? false
            let uploadPercent = item.value(
                forAttribute: NSMetadataUbiquitousItemPercentUploadedKey
            ) as? Double

            if isGather {
                AppLog.book.info("  [\(fileName)] status=\(status ?? "nil") dl%=\(percent ?? -1) uploading=\(isUploading) ul%=\(uploadPercent ?? -1)")
            }

            let newState: ICloudFileState
            if status == NSMetadataUbiquitousItemDownloadingStatusCurrent
                || status == NSMetadataUbiquitousItemDownloadingStatusDownloaded {
                newState = .current
            } else if let p = percent, p > 0, p < 100 {
                newState = .downloading(p / 100.0)
            } else {
                newState = .notDownloaded
            }

            if fileStates[fileName] != newState {
                fileStates[fileName] = newState
                AppLog.book.info("ICloudDownloadManager: \(fileName) → \(String(describing: newState))")
            }

            // 自動觸發未下載檔案的下載
            if newState == .notDownloaded, !triggeredFiles.contains(fileName) {
                triggeredFiles.insert(fileName)
                triggerDownload(for: fileName)
            }
        }
    }
}
