//
//  AppBootstrap.swift
//  Books & Vocab
//
//  SwiftData ModelContainer bootstrap + 失敗恢復路徑。
//  從 BooksAndVocabApp 拆出 — 集中管理 store schema、retry、fallback、purge。
//

import Foundation
import SwiftData

enum AppBootstrap {
    struct Outcome {
        let container: ModelContainer
        let failure: AppStartupFailure?
    }

    /// 完整 store schema 的唯一真相 — 新增 @Model 時只改這裡，
    /// 避免 6 處重複的型別清單彼此 drift。
    static let fullModelTypes: [any PersistentModel.Type] = [
        Book.self, VocabularyEntry.self, ReviewRecord.self, Notebook.self,
        PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self
    ]

    @MainActor
    static func run(arguments: [String] = ProcessInfo.processInfo.arguments) -> Outcome {
        // UI-test / probe 隔離（2026-06-10 事故）：fixture 會 wipe+seed
        // VocabularyEntry，掛真用戶 on-disk store 等於清掉整個本地單字庫；
        // CloudKit 一併斷開，真機跑 probe 不得污染 iCloud。fixture seed 端
        // 另有 in-memory guard（UITestFixtureSeed），雙層互為防線。
        // arguments 注入縫供單元測試釘住這一層（預設讀真實 ProcessInfo）。
        if AppRuntimeOptions.isUITesting(arguments: arguments) {
            let ephemeral = makeFallbackModelContainer()
            AuthManager.shared.modelContainer = ephemeral
            AppLog.app.info("UI-testing: ephemeral in-memory ModelContainer (no CloudKit)")
            return Outcome(container: ephemeral, failure: nil)
        }

        // 一次性自癒：清除舊版寫入的非法 review-event pull watermark，避免後端 400
        // 造成的背景同步死鎖（必須早於任何 sync 觸發）。
        KGService.migrateReviewEventBoundaryIfNeeded()

        let localConfig = ModelConfiguration(
            "LocalStore",
            schema: Schema([VocabularyEntry.self, ReviewRecord.self, Notebook.self, PodcastSeries.self, PodcastEpisode.self]),
            cloudKitDatabase: .none
        )

        let cloudConfig = ModelConfiguration(
            "CloudStore",
            schema: Schema([Book.self, PodcastProgress.self]),
            cloudKitDatabase: .automatic
        )

        do {
            let container = try ModelContainer(
                for: Schema(fullModelTypes),
                configurations: localConfig, cloudConfig
            )
            AuthManager.shared.modelContainer = container
            runMigrationIfNeeded(container: container)
            AppLog.app.info("ModelContainer initialized — models: \(fullModelTypes.map { String(describing: $0) }.joined(separator: ", "))")
            return Outcome(container: container, failure: nil)
        } catch {
            AppLog.app.error("ModelContainer init failed: \(error.localizedDescription) — attempting store reset")

            if let retryContainer = retryAfterStoreReset(localConfig: localConfig, cloudConfig: cloudConfig) {
                AuthManager.shared.modelContainer = retryContainer
                AppLog.app.warning("ModelContainer recovered after store reset — user data will re-sync from server")
                return Outcome(container: retryContainer, failure: nil)
            }

            AppLog.app.error("ModelContainer recovery failed — falling back to in-memory store")
            let fallback = makeFallbackModelContainer()
            // 仍把 fallback 交給 AuthManager，使降級後的記憶體 store 在帳號切換時
            // 一樣可被 clearLocalData 清除（與上方兩條成功路徑對齊，避免 nil 時靜默跳過清理）。
            AuthManager.shared.modelContainer = fallback
            return Outcome(
                container: fallback,
                failure: AppStartupFailure.storageInitialization(error: error)
            )
        }
    }

    private static func runMigrationIfNeeded(container: ModelContainer) {
        let migrationKey = "iCloudDataMigrationCompleted_v1"
        guard !UserDefaults.standard.bool(forKey: migrationKey) else { return }

        let localBooksDir = Book.localBooksDirectory
        guard let iCloudDir = Book.iCloudBooksDirectory else {
            AppLog.app.info("iCloud not available, deferring book migration")
            return
        }

        let files: [URL]
        do {
            files = try FileManager.default.contentsOfDirectory(
                at: localBooksDir,
                includingPropertiesForKeys: nil
            )
        } catch {
            AppLog.app.warning("Cannot list local books for migration: \(error.localizedDescription)")
            UserDefaults.standard.set(true, forKey: migrationKey)
            return
        }

        let epubs = files.filter { $0.pathExtension == "epub" }
        var failedCount = 0
        for file in epubs {
            let dest = iCloudDir.appendingPathComponent(file.lastPathComponent)
            if !FileManager.default.fileExists(atPath: dest.path) {
                do {
                    try FileManager.default.copyItem(at: file, to: dest)
                } catch {
                    failedCount += 1
                    AppLog.app.error("iCloud EPUB copy failed (\(file.lastPathComponent)): \(error.localizedDescription)")
                }
            }
        }

        if failedCount == 0 {
            UserDefaults.standard.set(true, forKey: migrationKey)
            AppLog.app.info("iCloud EPUB migration completed: \(epubs.count) files")
        } else {
            AppLog.app.warning("iCloud EPUB migration incomplete: \(failedCount)/\(epubs.count) failed, will retry next launch")
        }
    }

    /// 刪除本機 SwiftData store 後重建 ModelContainer（CloudKit store 從 iCloud 恢復）
    private static func retryAfterStoreReset(localConfig: ModelConfiguration, cloudConfig: ModelConfiguration) -> ModelContainer? {
        for storeURL in [localConfig.url, cloudConfig.url] {
            let storePaths = [storeURL, storeURL.appendingPathExtension("shm"), storeURL.appendingPathExtension("wal")]
            for path in storePaths {
                try? FileManager.default.removeItem(at: path)
            }
            AppLog.app.info("Removed store files at \(storeURL.lastPathComponent)")
        }

        // First try: dual-store (local + CloudKit)
        if let container = try? ModelContainer(
            for: Schema(fullModelTypes),
            configurations: localConfig, cloudConfig
        ) {
            return container
        }

        // Second try: all local, no CloudKit (iOS 26 CloudKit schema validation may fail)
        AppLog.app.warning("Dual-store retry failed — attempting single-store without CloudKit")
        let localOnlyConfig = ModelConfiguration(
            "LocalStore",
            schema: Schema(fullModelTypes),
            cloudKitDatabase: .none
        )
        return try? ModelContainer(
            for: Schema(fullModelTypes),
            configurations: localOnlyConfig
        )
    }

    private static func makeFallbackModelContainer() -> ModelContainer {
        do {
            return try ModelContainer(
                for: Schema(fullModelTypes),
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
        } catch {
            // Fail-soft: 最小 schema in-memory container 讓 AppStartupRecoveryView 仍可顯示而不直接 crash。
            AppLog.app.critical("Fallback ModelContainer init failed: \(error.localizedDescription); attempting minimal schema")
            if let minimal = try? ModelContainer(
                for: Notebook.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            ) {
                return minimal
            }
            AppLog.app.critical("Minimal ModelContainer init also failed: \(error.localizedDescription)")
            fatalError("Cannot create any ModelContainer: \(error)")
        }
    }

    /// Best-effort 刪除已知的 SwiftData store files —
    /// 與 retryAfterStoreReset 使用同樣的檔名（LocalStore / CloudStore + shm/wal）。
    static func purgeStoreFiles() {
        let localURL = ModelConfiguration(
            "LocalStore",
            schema: Schema([Notebook.self]),
            cloudKitDatabase: .none
        ).url
        let cloudURL = ModelConfiguration(
            "CloudStore",
            schema: Schema([Book.self]),
            cloudKitDatabase: .automatic
        ).url
        for storeURL in [localURL, cloudURL] {
            for path in [storeURL, storeURL.appendingPathExtension("shm"), storeURL.appendingPathExtension("wal")] {
                try? FileManager.default.removeItem(at: path)
            }
            AppLog.app.info("purgeStoreFiles: removed \(storeURL.lastPathComponent)")
        }
    }
}
