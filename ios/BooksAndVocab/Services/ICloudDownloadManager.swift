//
//  ICloudDownloadManager.swift
//  Books & Vocab
//

import Foundation

extension Notification.Name {
    /// LocalDataCleanerService 清除本機用戶資料後發出（帳號切換/登出）。
    /// ICloudDownloadManager 觀察此通知以重設狀態並重啟監控。
    static let localUserDataDidClear = Notification.Name("kg.localUserDataDidClear")
}

/// 將 NSMetadataItem 的下載屬性映射成 `ICloudFileState` 的純函式邏輯。
///
/// 抽成獨立、不依賴 NSMetadataItem 的純函式以便單元測試。核心修正：下載早期
/// NSMetadataQuery 常回報 `status == NotDownloaded` 且 `percent` 為 nil/0，但檔案
/// 其實已觸發下載。若直接降級成 `.notDownloaded`，書架 badge 會在雲朵與進度圈
/// 之間閃爍。只要檔案已在 triggeredFiles 內，percent 不可用時就沿用上次已知進度
/// （無前值則 `.downloading(0)`），不降級。
enum ICloudDownloadStateMapping {
    /// - Parameters:
    ///   - status: `NSMetadataUbiquitousItemDownloadingStatusKey` 字串值。
    ///   - percent: `NSMetadataUbiquitousItemPercentDownloadedKey`（0–100），nil = 未回報。
    ///   - hasError: `NSMetadataUbiquitousItemDownloadingErrorKey` 是否存在。
    ///   - isTriggered: 此檔是否已在 `triggeredFiles` 內（已觸發下載）。
    ///   - previous: 上次已知狀態（用於 percent 不可用時保留進度）。
    static func resolve(
        status: String?,
        percent: Double?,
        hasError: Bool,
        isTriggered: Bool,
        previous: ICloudFileState?
    ) -> ICloudFileState {
        if status == NSMetadataUbiquitousItemDownloadingStatusCurrent
            || status == NSMetadataUbiquitousItemDownloadingStatusDownloaded {
            return .current
        }
        if hasError {
            // 中途下載錯誤 → terminal failed，允許使用者重試。
            return .failed
        }
        if let p = percent, p > 0, p < 100 {
            return .downloading(p / 100.0)
        }
        // percent 不可用（nil 或 0）。已觸發下載的檔處於下載早期窗口 → 維持
        // .downloading，沿用上次進度，避免 badge 閃回 .notDownloaded。
        if isTriggered {
            if case let .downloading(prev)? = previous {
                return .downloading(prev)
            }
            return .downloading(0)
        }
        return .notDownloaded
    }
}

/// iCloud 檔案下載狀態
enum ICloudFileState: Equatable {
    /// 已下載，本機可用
    case current
    /// 下載中，進度 0.0–1.0
    case downloading(Double)
    /// 未下載，等待觸發
    case notDownloaded
    /// 下載失敗（terminal）— 等待使用者重試
    case failed
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
    // 帳號切換 observers 與 NSMetadataQuery 生命週期無關，在 init 訂閱、deinit 取消，
    // 不受 startMonitoring/stopMonitoring 影響，確保外部直接呼叫 stopMonitoring() 後
    // 仍能收到帳號切換通知。
    // nonisolated(unsafe)：deinit 是 nonisolated，無法存取 @MainActor 屬性；
    // deinit 時物件即將釋放，無並發存取，unsafe 是安全的。
    nonisolated(unsafe) private var identityObserver: Any?
    nonisolated(unsafe) private var userDataClearObserver: Any?
    private var triggeredFiles: Set<String> = []

    init() {
        identityObserver = NotificationCenter.default.addObserver(
            forName: .NSUbiquityIdentityDidChange,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.reset() }
        }
        userDataClearObserver = NotificationCenter.default.addObserver(
            forName: .localUserDataDidClear,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.reset() }
        }
    }

    deinit {
        MainActor.assumeIsolated {
            if let o = identityObserver { NotificationCenter.default.removeObserver(o) }
            if let o = userDataClearObserver { NotificationCenter.default.removeObserver(o) }
        }
    }

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

        let booksDir = containerURL.appendingPathComponent("Documents/Books")
        // 列出目錄中已知的檔案（含 .icloud placeholder）
        if let contents = try? fm.contentsOfDirectory(atPath: booksDir.path) {
            AppLog.book.info("ICloudDownloadManager: Books directory has \(contents.count) entries: \(contents.joined(separator: ", "))")
        } else {
            AppLog.book.info("ICloudDownloadManager: Books directory is empty or not accessible")
        }

        let query = NSMetadataQuery()
        query.searchScopes = [NSMetadataQueryUbiquitousDocumentsScope]
        query.predicate = NSPredicate(
            format: "%K LIKE '*.epub' OR %K LIKE '*.pdf'",
            NSMetadataItemFSNameKey, NSMetadataItemFSNameKey
        )

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

    /// 停止監控（只停 NSMetadataQuery；帳號切換 observers 不受影響）
    func stopMonitoring() {
        metadataQuery?.stop()
        metadataQuery = nil
        if let o = gatherObserver { NotificationCenter.default.removeObserver(o) }
        if let o = updateObserver { NotificationCenter.default.removeObserver(o) }
        gatherObserver = nil
        updateObserver = nil
    }

    /// 帳號切換時重設所有狀態並重新開始監控新帳號的 iCloud 容器。
    func reset() {
        AppLog.book.info("ICloudDownloadManager: reset for account change")
        stopMonitoring()
        fileStates = [:]
        triggeredFiles = []
        hasGathered = false
        startMonitoring()
    }

    /// 手動觸發特定檔案下載
    func triggerDownload(for fileName: String) {
        guard let dir = Book.iCloudBooksDirectory else { return }
        let url = dir.appendingPathComponent(fileName)
        do {
            try FileManager.default.startDownloadingUbiquitousItem(at: url)
            if fileStates[fileName] == nil
                || fileStates[fileName] == .notDownloaded
                || fileStates[fileName] == .failed {
                fileStates[fileName] = .downloading(0)
            }
            AppLog.book.info("ICloudDownloadManager: download triggered — \(fileName)")
        } catch {
            // 觸發失敗為 terminal error：標記 .failed 並允許重觸發
            fileStates[fileName] = .failed
            triggeredFiles.remove(fileName)
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
            // 下載過程中的錯誤（中途失敗 NSMetadataQuery 不改 status，靠此 key 偵測）
            let downloadError = item.value(
                forAttribute: NSMetadataUbiquitousItemDownloadingErrorKey
            ) as? NSError

            if isGather {
                AppLog.book.info("  [\(fileName)] status=\(status ?? "nil") dl%=\(percent ?? -1) uploading=\(isUploading) ul%=\(uploadPercent ?? -1) err=\(downloadError?.localizedDescription ?? "nil")")
            }

            let newState = ICloudDownloadStateMapping.resolve(
                status: status,
                percent: percent,
                hasError: downloadError != nil,
                isTriggered: triggeredFiles.contains(fileName),
                previous: fileStates[fileName]
            )
            if let err = downloadError {
                AppLog.book.error("ICloudDownloadManager: download error — \(fileName): \(err.localizedDescription)")
            }

            if fileStates[fileName] != newState {
                fileStates[fileName] = newState
                AppLog.book.info("ICloudDownloadManager: \(fileName) → \(String(describing: newState))")
            }

            // 失敗後解除觸發鎖，讓使用者重試（或下次 query 變回 notDownloaded）可重觸發
            if newState == .failed {
                triggeredFiles.remove(fileName)
            }

            // 自動觸發未下載檔案的下載（.failed 不自動重觸發，避免持續錯誤無限迴圈）
            if newState == .notDownloaded, !triggeredFiles.contains(fileName) {
                triggeredFiles.insert(fileName)
                triggerDownload(for: fileName)
            }
        }
    }

    #if DEBUG
    /// 測試用：直接寫入 fileStates，讓 reset() 的副作用（清空）可被觀察。
    func setFileStateForTesting(_ state: ICloudFileState, for fileName: String) {
        fileStates[fileName] = state
    }
    #endif
}
