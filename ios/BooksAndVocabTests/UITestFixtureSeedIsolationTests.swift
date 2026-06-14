import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

/// Fixture seeding 的資料安全防線。
///
/// 事故（2026-06-10）：`-ui-testing -seedFixture:todayReview:deck` 在真機上
/// 對「真實 on-disk store」先刪光全部 VocabularyEntry 再種量測卡——bootstrap
/// 沒有為 UI-testing 提供隔離容器，使用者整個本地單字庫被 wipe。
/// 後端因刪除只走 pending+delete 意圖（fixture 是硬刪）而倖免。
///
/// 契約（雙層防禦的 seed 層）：fixture seeding 只允許對「全 in-memory」容器
/// 動手；任何 persistent 配置一律拒絕且不得改動任何資料。
/// .serialized：每案例各建 SwiftData 容器，平行跑會在共享 entity 註冊上
/// 互踩（實測 signal abrt）；序列化讓容器生命週期不重疊。
@Suite(.serialized)
@MainActor
struct UITestFixtureSeedIsolationTests {
    private static let seedArguments = ["-ui-testing", "-seedFixture:todayReview:deck"]
    private static var supportDirectory: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Support", isDirectory: true)
    }

    private static var reviewProbeWorldData: Data {
        let entries = (0..<40).map { index in
            """
            {
              "word": "probeword\(index)",
              "translation": "probe",
              "context": "probe context \(index)",
              "bookTitle": "Review Probe Fixture",
              "reviewMode": "recognition",
              "reviewExamples": ["probe context \(index)"],
              "syncStatus": 1,
              "actionType": "add",
              "isArchived": false,
              "isExcludedFromReader": false,
              "graphLinksByKind": {}
            }
            """
        }.joined(separator: ",")
        return Data(
            """
            {
              "schema": "kg.fixture.dataset.v2",
              "datasetID": "test-review-probe",
              "assets": {
                "books": {},
                "audio": {},
                "subtitles": {},
                "text": {},
                "images": {}
              },
              "preferences": {
                "userDefaults": {},
                "ubiquitousKeyValueStore": {}
              },
              "auth": {},
              "entitlements": {},
              "settings": {},
              "bookshelf": {},
              "todayReview": {},
              "notebook": {},
              "podcast": {},
              "runtimePodcast": {},
              "reader": {},
              "vocabulary": {},
              "reviewDeck": {
                "probe": {
                  "notebookRemoteId": "default",
                  "notebookName": "Probe",
                  "notebookSyncStatus": 1,
                  "entries": [\(entries)]
                }
              }
            }
            """.utf8
        )
    }

    private static func fixtureSeedSourceURLs() throws -> [URL] {
        try FileManager.default
            .contentsOfDirectory(at: supportDirectory, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix("UITestFixtureSeed") && $0.pathExtension == "swift" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    private func makeSchema() -> Schema {
        Schema([VocabularyEntry.self, ReviewRecord.self, Notebook.self])
    }

    @Test func fixtureSeedFailuresAreHardFailures() throws {
        let forbiddenSnippets = [
            "AppLog.app.warning(\"Unknown",
            "AppLog.app.error(\"Failed to seed",
        ]

        for url in try Self.fixtureSeedSourceURLs() {
            let source = try String(contentsOf: url, encoding: .utf8)
            for snippet in forbiddenSnippets {
                #expect(
                    !source.contains(snippet),
                    "\(url.lastPathComponent) must fail hard instead of log-only for \(snippet)"
                )
            }
        }
    }

    @Test func seedRefusesPersistentStore() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("seed-guard-\(UUID().uuidString).store")
        defer {
            for suffix in ["", "-shm", "-wal"] {
                try? FileManager.default.removeItem(atPath: url.path + suffix)
            }
        }
        let schema = makeSchema()
        let config = ModelConfiguration(schema: schema, url: url, cloudKitDatabase: .none)
        let container = try ModelContainer(for: schema, configurations: config)

        let real = VocabularyEntry(
            word: "irreplaceable",
            translation: "使用者的真實詞條",
            context: "real user data",
            bookTitle: "Real Book"
        )
        container.mainContext.insert(real)
        try container.mainContext.save()

        try FixtureDatasetStore.withTestingData(Self.reviewProbeWorldData) {
            UITestFixtureSeed.injectIfNeeded(into: container, arguments: Self.seedArguments)
        }

        let words = try container.mainContext
            .fetch(FetchDescriptor<VocabularyEntry>())
            .map(\.word)
        #expect(words == ["irreplaceable"], "persistent store 不可被 wipe/seed，實際: \(words.count) 筆")
        #expect(!words.contains { $0.hasPrefix("probeword") })
    }

    /// 混合配置（部分 persistent）必須整體拒絕——allSatisfy 語意核心。
    @Test func seedRefusesMixedConfigurationContainer() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("seed-guard-mixed-\(UUID().uuidString).store")
        defer {
            for suffix in ["", "-shm", "-wal"] {
                try? FileManager.default.removeItem(atPath: url.path + suffix)
            }
        }
        // 拆分鏡像 app 真實形狀（vocab 三件組一個 store、Book 另一個）——
        // 有關聯的模型不可跨 store 拆，亂拆 container init 會 throw。
        let memoryConfig = ModelConfiguration(
            schema: Schema([VocabularyEntry.self, ReviewRecord.self, Notebook.self]),
            isStoredInMemoryOnly: true
        )
        let diskConfig = ModelConfiguration(
            schema: Schema([Book.self]),
            url: url,
            cloudKitDatabase: .none
        )
        let container = try ModelContainer(
            for: Schema([VocabularyEntry.self, ReviewRecord.self, Notebook.self, Book.self]),
            configurations: memoryConfig, diskConfig
        )

        try FixtureDatasetStore.withTestingData(Self.reviewProbeWorldData) {
            UITestFixtureSeed.injectIfNeeded(into: container, arguments: Self.seedArguments)
        }

        let count = try container.mainContext.fetchCount(FetchDescriptor<VocabularyEntry>())
        #expect(count == 0, "混合配置容器必須整體拒絕 seeding")
    }

    /// 第一層防線（bootstrap）：-ui-testing 必須拿到全 in-memory 容器。
    /// 回歸症狀若無此測會以「seed 靜默拒絕→deck=0」的下游困惑形式出現。
    @Test @MainActor func bootstrapUITestingYieldsEphemeralContainer() throws {
        let previous = AuthManager.shared.modelContainer
        defer { AuthManager.shared.modelContainer = previous }

        let outcome = AppBootstrap.run(arguments: ["-ui-testing"])

        let configs = outcome.container.configurations
        let allInMemory = configs.allSatisfy { $0.isStoredInMemoryOnly }
        #expect(!configs.isEmpty)
        #expect(allInMemory)
        #expect(outcome.failure == nil)
    }

    @Test func seedSeedsEphemeralStore() throws {
        let schema = makeSchema()
        let config = ModelConfiguration(schema: schema, isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        let container = try ModelContainer(for: schema, configurations: config)

        try FixtureDatasetStore.withTestingData(Self.reviewProbeWorldData) {
            UITestFixtureSeed.injectIfNeeded(into: container, arguments: Self.seedArguments)
        }

        let count = try container.mainContext.fetchCount(FetchDescriptor<VocabularyEntry>())
        #expect(count == 40, "in-memory 容器 seeding 必須照常運作")
    }
}
