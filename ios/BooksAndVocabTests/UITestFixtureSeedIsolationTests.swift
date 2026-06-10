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
@MainActor
struct UITestFixtureSeedIsolationTests {
    private static let seedArguments = ["-ui-testing", "-seedFixture:todayReview:deck"]

    private func makeSchema() -> Schema {
        Schema([VocabularyEntry.self, ReviewRecord.self, Notebook.self])
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

        UITestFixtureSeed.injectIfNeeded(into: container, arguments: Self.seedArguments)

        let words = try container.mainContext
            .fetch(FetchDescriptor<VocabularyEntry>())
            .map(\.word)
        #expect(words == ["irreplaceable"], "persistent store 不可被 wipe/seed，實際: \(words.count) 筆")
        #expect(!words.contains { $0.hasPrefix("probeword") })
    }

    @Test func seedSeedsEphemeralStore() throws {
        let schema = makeSchema()
        let config = ModelConfiguration(schema: schema, isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        let container = try ModelContainer(for: schema, configurations: config)

        UITestFixtureSeed.injectIfNeeded(into: container, arguments: Self.seedArguments)

        let count = try container.mainContext.fetchCount(FetchDescriptor<VocabularyEntry>())
        #expect(count == 40, "in-memory 容器 seeding 必須照常運作")
    }
}
