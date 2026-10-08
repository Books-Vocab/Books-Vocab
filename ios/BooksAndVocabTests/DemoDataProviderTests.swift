import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

/// DemoDataProvider 的注入／移除契約（#2054）：demo 卡片必須完整落地、標記為 demo、
/// 圖譜連結可解析到已注入的卡片；移除只刪 demo 列、不碰使用者資料；SwiftData 錯誤不得被 `try?` 吞掉。
struct DemoDataProviderTests {
    private func makeContainer() throws -> ModelContainer {
        let schema = Schema([
            Book.self,
            VocabularyEntry.self,
            ReviewRecord.self,
            Notebook.self,
            PodcastSeries.self,
            PodcastEpisode.self,
            PodcastProgress.self
        ])
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        return try ModelContainer(for: schema, configurations: [config])
    }

    /// 每次都用新的 ModelContext 讀，證明資料已 save 進 store，而不是只停在 provider 的 context。
    private func allEntries(in container: ModelContainer) throws -> [VocabularyEntry] {
        try ModelContext(container).fetch(FetchDescriptor<VocabularyEntry>())
    }

    @Test func injectThenRemoveRoundTrip() throws {
        let container = try makeContainer()
        let seedContext = ModelContext(container)
        let userWord = "user-seeded-word"
        seedContext.insert(VocabularyEntry(word: userWord, translation: "t", context: "c", bookTitle: "User Book"))
        try seedContext.save()

        DemoDataProvider.injectDemoEntries(into: container)

        let afterInject = try allEntries(in: container)
        let injected = afterInject.filter { $0.bookTitle == DemoDataProvider.demoBookTitle }
        #expect(!injected.isEmpty)
        #expect(afterInject.count == injected.count + 1, "inject must only add demo-book rows")
        let unflaggedWords = injected.filter { !$0.isDemoEntry }.map(\.word)
        #expect(unflaggedWords.isEmpty, "every injected row must be flagged so remove can find it: \(unflaggedWords)")

        let demoFlagged = try ModelContext(container).fetch(
            FetchDescriptor(predicate: #Predicate<VocabularyEntry> { $0.isDemoEntry == true })
        )
        #expect(demoFlagged.count == injected.count)

        let cardIds = injected.compactMap(\.kgCardId)
        #expect(cardIds.count == injected.count, "every demo entry needs a kgCardId for graph links")
        #expect(Set(cardIds).count == cardIds.count, "demo kgCardIds must be unique")

        let linkedIds = Set(DemoDataProvider.demoGraphLinks.flatMap { [$0.fromId, $0.toId] })
        #expect(!linkedIds.isEmpty)
        #expect(linkedIds.subtracting(cardIds).isEmpty, "dangling demo graph link ids: \(linkedIds.subtracting(cardIds).sorted())")

        DemoDataProvider.removeDemoEntries(from: container)

        let afterRemove = try allEntries(in: container)
        let remainingDemoCount = afterRemove.filter { $0.isDemoEntry }.count
        let remainingWords = afterRemove.map(\.word)
        #expect(remainingDemoCount == 0)
        #expect(remainingWords == [userWord], "remove must leave non-demo entries untouched")
    }

    @Test func demoDataProviderNeverSwallowsSwiftDataErrors() throws {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Services/DemoDataProvider.swift")
        let source = try String(contentsOf: url, encoding: .utf8)

        #expect(!source.contains("try? context.save()"), "DemoDataProvider must save via safeSave()")
        #expect(!source.contains("try? context.fetch"), "DemoDataProvider must not swallow fetch errors")

        let removeStart = try #require(source.range(of: "static func removeDemoEntries"))
        let removeEnd = try #require(source.range(of: "static var demoGraphLinks", range: removeStart.upperBound..<source.endIndex))
        let removeBody = source[removeStart.lowerBound..<removeEnd.lowerBound]
        #expect(removeBody.contains("AppLog.data.error"), "removeDemoEntries must log fetch failures")
    }
}
