#if os(iOS)
import Foundation
import ReadiumShared

struct ReaderPublicationLoadResult {
    let publication: Publication
    /// 唯一詞擷取以 closure 回傳，而非預先包成 unstructured `Task`，
    /// 讓呼叫端可在自身結構化作用域（`.task`）內 `await`，
    /// view 中途 dismiss 時隨作用域取消，不留 fire-and-forget 殘留。
    /// MainActor-isolated（與 loader / ReadiumServing 一致，Publication 非 Sendable）。
    let extractUniqueWords: @MainActor () async -> Set<String>
}

@MainActor
struct ReaderPublicationLoader {
    let readiumService: any ReadiumServing
    let downloadManager: ICloudDownloadManager

    func loadPublication(
        for book: Book,
        updatePhase: @escaping @MainActor (String) -> Void
    ) async throws -> ReaderPublicationLoadResult {
        let url = book.fileURL

        if !FileManager.default.isReadableFile(atPath: url.path) {
            try await waitForICloudFile(at: url, updatePhase: updatePhase)
        }

        updatePhase(L10n.string("開啟書本…"))
        let publication = try await readiumService.openPublication(at: url)
        updatePhase(L10n.string("渲染頁面…"))

        return ReaderPublicationLoadResult(
            publication: publication,
            extractUniqueWords: { await readiumService.extractUniqueWords(from: publication) }
        )
    }

    private func waitForICloudFile(
        at url: URL,
        updatePhase: @escaping @MainActor (String) -> Void
    ) async throws {
        let fm = FileManager.default
        let fileName = url.lastPathComponent

        downloadManager.triggerDownload(for: fileName)
        updatePhase(L10n.string("正在從 iCloud 下載…"))

        var downloadTriggered = false
        do {
            try fm.startDownloadingUbiquitousItem(at: url)
            downloadTriggered = true
        } catch {
            AppLog.readium.warning("startDownloadingUbiquitousItem failed for \(fileName): \(error.localizedDescription)")
        }
        if !downloadTriggered {
            AppLog.readium.info("File not yet known to iCloud, waiting for sync: \(fileName)")
            updatePhase(L10n.string("等待 iCloud 同步…"))
        }

        let deadline = Date().addingTimeInterval(ReaderMetrics.iCloudWaitTimeout)
        var retried = false
        while Date() < deadline {
            if fm.isReadableFile(atPath: url.path) {
                AppLog.readium.info("iCloud file ready: \(fileName)")
                return
            }

            if let state = downloadManager.state(for: fileName) {
                switch state {
                case .current:
                    try await Task.sleep(for: .seconds(ReaderMetrics.iCloudCurrentPollInterval))
                    continue
                case .downloading(let progress):
                    updatePhase(L10n.format("正在從 iCloud 下載… %@%%", String(Int(progress * 100))))
                case .notDownloaded:
                    break
                case .failed:
                    AppLog.readium.error("iCloud download failed for: \(fileName)")
                    throw iCloudLoadError(
                        code: 4,
                        message: L10n.string("iCloud 下載失敗。請確認網路連線後，在書架上點按書本重試下載。")
                    )
                }
            }

            if !retried && !downloadTriggered {
                let placeholder = url.deletingLastPathComponent()
                    .appendingPathComponent(".\(fileName).icloud")
                if fm.fileExists(atPath: placeholder.path) {
                    do {
                        try fm.startDownloadingUbiquitousItem(at: url)
                    } catch {
                        AppLog.readium.warning("startDownloadingUbiquitousItem failed for \(fileName): \(error.localizedDescription)")
                    }
                    retried = true
                    updatePhase(L10n.string("正在從 iCloud 下載…"))
                    AppLog.readium.info("Placeholder appeared, download triggered: \(fileName)")
                }
            }

            try await Task.sleep(for: .seconds(ReaderMetrics.iCloudWaitPollInterval))
        }

        AppLog.readium.error("iCloud file wait timed out: \(fileName)")
        throw iCloudLoadError(
            code: 3,
            message: L10n.string("iCloud 同步逾時。可能原因：\n• 原始裝置尚未完成上傳\n• 網路連線不穩定\n\n請確認兩台裝置都已登入相同 Apple ID 並開啟 iCloud 雲碟。")
        )
    }

    private func iCloudLoadError(code: Int, message: String) -> NSError {
        NSError(domain: "Book", code: code, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
#endif
