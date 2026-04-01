#if os(iOS)
import Foundation
import ReadiumShared

struct ReaderPublicationLoadResult {
    let publication: Publication
    let uniqueWordsTask: Task<Set<String>, Never>
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

        let uniqueWordsTask = Task(priority: .utility) {
            await readiumService.extractUniqueWords(from: publication)
        }
        return ReaderPublicationLoadResult(publication: publication, uniqueWordsTask: uniqueWordsTask)
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

        let deadline = Date().addingTimeInterval(120)
        var retried = false
        while Date() < deadline {
            if fm.isReadableFile(atPath: url.path) {
                AppLog.readium.info("iCloud file ready: \(fileName)")
                return
            }

            if let state = downloadManager.state(for: fileName) {
                switch state {
                case .current:
                    try await Task.sleep(nanoseconds: 200_000_000)
                    continue
                case .downloading(let progress):
                    updatePhase(L10n.string("正在從 iCloud 下載… \(Int(progress * 100))%"))
                case .notDownloaded:
                    break
                }
            }

            if !retried && !downloadTriggered {
                let placeholder = url.deletingLastPathComponent()
                    .appendingPathComponent(".\(fileName).icloud")
                if fm.fileExists(atPath: placeholder.path) {
                    try? fm.startDownloadingUbiquitousItem(at: url)
                    retried = true
                    updatePhase(L10n.string("正在從 iCloud 下載…"))
                    AppLog.readium.info("Placeholder appeared, download triggered: \(fileName)")
                }
            }

            try await Task.sleep(nanoseconds: 500_000_000)
        }

        AppLog.readium.error("iCloud file wait timed out: \(fileName)")
        throw NSError(
            domain: "Book",
            code: 3,
            userInfo: [NSLocalizedDescriptionKey: L10n.string(
                "iCloud 同步逾時。可能原因：\n• 原始裝置尚未完成上傳\n• 網路連線不穩定\n\n請確認兩台裝置都已登入相同 Apple ID 並開啟 iCloud 雲碟。"
            )]
        )
    }
}
#endif
