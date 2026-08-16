//
//  AppBootstrap.swift
//  Books & Vocab
//
//  SwiftData ModelContainer bootstrap + 失敗恢復路徑。
//  從 BooksAndVocabApp 拆出 — 集中管理 store schema、fallback、explicit purge。
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
        PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self,
        SharedDeck.self
    ]

    @MainActor
    static func run(
        arguments: [String] = ProcessInfo.processInfo.arguments,
        persistentContainerFactory: (() throws -> ModelContainer)? = nil
    ) -> Outcome {
        // UI-test / probe 隔離（2026-06-10 事故）：fixture 會 wipe+seed
        // VocabularyEntry，掛真用戶 on-disk store 等於清掉整個本地單字庫；
        // CloudKit 一併斷開，真機跑 probe 不得污染 iCloud。fixture seed 端
        // 另有 in-memory guard（UITestFixtureSeed），雙層互為防線。
        // arguments 注入縫供單元測試釘住這一層（預設讀真實 ProcessInfo）。
        if AppRuntimeOptions.isUITesting(arguments: arguments) {
            let ephemeral = makeFallbackModelContainer()
            AuthManager.shared.modelContainer = ephemeral
            CloudKitMirroringMonitor.shared.configure(cloudKitEnabled: false)
            AppLog.app.info("UI-testing: ephemeral in-memory ModelContainer (no CloudKit)")
            return Outcome(container: ephemeral, failure: nil)
        }

        // 一次性自癒：清除舊版寫入的非法 review-event pull watermark，避免後端 400
        // 造成的背景同步死鎖（必須早於任何 sync 觸發）。
        KGService.migrateReviewEventBoundaryIfNeeded()

        let localConfig = ModelConfiguration(
            "LocalStore",
            schema: Schema([VocabularyEntry.self, ReviewRecord.self, Notebook.self, PodcastSeries.self, PodcastEpisode.self, SharedDeck.self]),
            cloudKitDatabase: .none
        )

        let cloudConfig = ModelConfiguration(
            "CloudStore",
            schema: Schema([Book.self, PodcastProgress.self]),
            cloudKitDatabase: .automatic
        )

        do {
            let container: ModelContainer
            if let persistentContainerFactory {
                container = try persistentContainerFactory()
            } else {
                container = try ModelContainer(
                    for: Schema(fullModelTypes),
                    configurations: localConfig, cloudConfig
                )
            }
            AuthManager.shared.modelContainer = container
            CloudKitMirroringMonitor.shared.configure(cloudKitEnabled: true)
            CloudKitMirroringMonitor.shared.start()
            runMigrationIfNeeded(container: container)
            AppLog.app.info("ModelContainer initialized — models: \(fullModelTypes.map { String(describing: $0) }.joined(separator: ", "))")
            return Outcome(container: container, failure: nil)
        } catch {
            // A persistent-store initialization error can be a migration or
            // CloudKit failure. Never turn that signal into an automatic
            // destructive reset: pending local cards may not exist remotely.
            // Keep the files intact and let the explicit recovery UI own purge.
            AppLog.app.error("ModelContainer init failed: \(error.localizedDescription) — preserving stores and entering recovery")
            let fallback = makeFallbackModelContainer()
            // 仍把 fallback 交給 AuthManager，使降級後的記憶體 store 在帳號切換時
            // 一樣可被 clearLocalData 清除（與上方兩條成功路徑對齊，避免 nil 時靜默跳過清理）。
            AuthManager.shared.modelContainer = fallback
            CloudKitMirroringMonitor.shared.configure(cloudKitEnabled: false)
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

    static func storeArtifactURLs(for storeURL: URL) -> [URL] {
        ["", "-shm", "-wal"].map { suffix in
            URL(fileURLWithPath: storeURL.path + suffix)
        }
    }

    /// Explicit recovery action only. Returns false when any existing SQLite
    /// artifact could not be removed, so the UI does not report a false reset.
    @discardableResult
    static func purgeStoreFiles(at storeURLs: [URL]? = nil) -> Bool {
        let resolvedStoreURLs: [URL]
        if let storeURLs {
            resolvedStoreURLs = storeURLs
        } else {
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
            resolvedStoreURLs = [localURL, cloudURL]
        }

        var succeeded = true
        for storeURL in resolvedStoreURLs {
            for artifactURL in storeArtifactURLs(for: storeURL) {
                guard FileManager.default.fileExists(atPath: artifactURL.path) else { continue }
                do {
                    try FileManager.default.removeItem(at: artifactURL)
                } catch {
                    succeeded = false
                    AppLog.app.error("purgeStoreFiles failed for \(artifactURL.lastPathComponent): \(error.localizedDescription)")
                }
            }
            AppLog.app.info("purgeStoreFiles: processed \(storeURL.lastPathComponent)")
        }
        return succeeded
    }
}
