#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
final class BookMetadataRepairServiceTests {
    // 記錄 makeService 建立的 UserDefaults suite，deinit 時清掉，避免測試 plist 殘留
    // 在 test host 的 Library/Preferences 累積（Swift Testing 每測試一實例、釋放觸發 deinit）。
    private var createdSuiteNames: [String] = []

    deinit {
        for suite in createdSuiteNames {
            UserDefaults.standard.removePersistentDomain(forName: suite)
        }
    }

    // MARK: - Fixtures

    @MainActor
    final class FakeExtractor: BookMetadataExtracting {
        enum Outcome {
            case success(ExtractedBookMetadata)
            case failure(Error)
        }
        var outcome: Outcome
        private(set) var callCount = 0
        private(set) var calledURLs: [URL] = []

        init(_ outcome: Outcome) { self.outcome = outcome }

        func extractMetadata(fromEPUBAt url: URL) async throws -> ExtractedBookMetadata {
            callCount += 1
            calledURLs.append(url)
            switch outcome {
            case .success(let metadata): return metadata
            case .failure(let error): throw error
            }
        }
    }

    struct ExtractFailure: Error {}

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

    private func makeTempRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("BookMetadataRepairTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    private func makeService(extractor: any BookMetadataExtracting, root: URL) -> BookMetadataRepairService {
        // 每個 service 一份隔離的 UserDefaults suite，避免 skip 標記跨測試外洩；
        // suite 名記錄起來於 deinit 清理。
        let suiteName = "BookMetadataRepairTests-\(UUID().uuidString)"
        createdSuiteNames.append(suiteName)
        return BookMetadataRepairService(
            extractor: extractor,
            manifestStore: BookManifestStore(rootDirectory: root),
            userDefaults: UserDefaults(suiteName: suiteName)!,
            fileURLProvider: { root.appendingPathComponent($0.epubFileName) }
        )
    }

    private func writeReadableFile(_ fileName: String, in root: URL) throws {
        try Data("epub".utf8).write(to: root.appendingPathComponent(fileName))
    }

    // MARK: - Tests

    @Test func repairsDirtyRowAndManifestPreservingReadingPosition() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        let fileName = "F9634750-1CEE-4E8E-A7A7-13594801B886.epub"
        try writeReadableFile(fileName, in: root)

        // 髒 row：UUID title、空 author、nil cover，但有真實閱讀進度與 notebook 綁定
        let bookId = UUID()
        let book = Book(title: "F9634750-1CEE-4E8E-A7A7-13594801B886", author: "", fileName: fileName, format: .epub)
        book.id = bookId
        book.progression = 0.5
        book.lastReadLocatorJSON = #"{"href":"chapter"}"#
        book.dateLastRead = Date(timeIntervalSince1970: 1000)
        book.preferredNotebookId = "nb-1"
        context.insert(book)
        try context.save()

        // 髒 manifest（同樣污染）
        let store = BookManifestStore(rootDirectory: root)
        try store.write(BookManifest(
            bookId: bookId,
            fileName: fileName,
            originalFileName: "Real.epub",
            title: "F9634750-1CEE-4E8E-A7A7-13594801B886",
            author: "",
            format: .epub,
            coverImageData: nil,
            dateAdded: Date(timeIntervalSince1970: 1),
            dateLastRead: Date(timeIntervalSince1970: 1000),
            progression: 0.5,
            lastReadLocatorJSON: #"{"href":"chapter"}"#,
            preferredNotebookId: "nb-1"
        ))

        let extractor = FakeExtractor(.success(ExtractedBookMetadata(
            title: "The Real Title",
            author: "Real Author",
            coverImageData: Data([1, 2, 3])
        )))
        let service = makeService(extractor: extractor, root: root)

        let repaired = await service.repairIfNeeded(context: context)

        #expect(repaired == 1)
        #expect(extractor.callCount == 1)

        let saved = try #require(try context.fetch(FetchDescriptor<Book>()).first)
        #expect(saved.title == "The Real Title")
        #expect(saved.author == "Real Author")
        #expect(saved.coverImageData == Data([1, 2, 3]))
        // 閱讀位置 / 綁定保留
        #expect(saved.progression == 0.5)
        #expect(saved.lastReadLocatorJSON == #"{"href":"chapter"}"#)
        #expect(saved.preferredNotebookId == "nb-1")

        // manifest 同步修好且保留 progress/notebook/dateAdded/originalFileName
        let manifest = try store.read(bookId: bookId)
        #expect(manifest.title == "The Real Title")
        #expect(manifest.author == "Real Author")
        #expect(manifest.coverImageData == Data([1, 2, 3]))
        #expect(manifest.progression == 0.5)
        #expect(manifest.lastReadLocatorJSON == #"{"href":"chapter"}"#)
        #expect(manifest.preferredNotebookId == "nb-1")
        #expect(manifest.dateAdded == Date(timeIntervalSince1970: 1))
        #expect(manifest.originalFileName == "Real.epub")
    }

    @Test func doesNotWriteWhenExtractedMetadataIsUnusable() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        let fileName = "D8D20CE3-F60E-45E0-9410-12D0A5DCCD78.epub"
        try writeReadableFile(fileName, in: root)
        let book = Book(title: "D8D20CE3-F60E-45E0-9410-12D0A5DCCD78", author: "", fileName: fileName, format: .epub)
        context.insert(book)
        try context.save()

        // extractor 回傳 Readium 佔位值（Untitled / Unknown / nil cover）
        let extractor = FakeExtractor(.success(ExtractedBookMetadata(
            title: "Untitled",
            author: "Unknown",
            coverImageData: nil
        )))
        let service = makeService(extractor: extractor, root: root)

        let repaired = await service.repairIfNeeded(context: context)

        #expect(repaired == 0)
        #expect(extractor.callCount == 1)
        let saved = try #require(try context.fetch(FetchDescriptor<Book>()).first)
        #expect(saved.title == "D8D20CE3-F60E-45E0-9410-12D0A5DCCD78")
        #expect(saved.author == "")
        #expect(saved.coverImageData == nil)
        // 不污染 manifest
        let manifest = try? BookManifestStore(rootDirectory: root).read(bookId: book.id)
        #expect(manifest == nil)
    }

    @Test func cleanRowIsNotACandidate() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        let fileName = "clean.epub"
        try writeReadableFile(fileName, in: root)
        let book = Book(title: "Already Clean", author: "Jane Doe", coverImageData: Data([9]), fileName: fileName, format: .epub)
        context.insert(book)
        try context.save()

        let extractor = FakeExtractor(.success(ExtractedBookMetadata(title: "X", author: "Y", coverImageData: Data([1]))))
        let service = makeService(extractor: extractor, root: root)

        let repaired = await service.repairIfNeeded(context: context)

        #expect(repaired == 0)
        #expect(extractor.callCount == 0)
        let saved = try #require(try context.fetch(FetchDescriptor<Book>()).first)
        #expect(saved.title == "Already Clean")
        #expect(saved.author == "Jane Doe")
        #expect(saved.coverImageData == Data([9]))
    }

    @Test func unreadableFileIsSkippedWithoutCallingExtractor() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        // 不寫檔 → isReadableFile false（模擬 .icloud placeholder / 未下載）
        let fileName = "00000000-0000-0000-0000-000000000000.epub"
        let book = Book(title: "00000000-0000-0000-0000-000000000000", author: "", fileName: fileName, format: .epub)
        context.insert(book)
        try context.save()

        let extractor = FakeExtractor(.success(ExtractedBookMetadata(title: "X", author: "Y", coverImageData: Data([1]))))
        let service = makeService(extractor: extractor, root: root)

        let repaired = await service.repairIfNeeded(context: context)

        #expect(repaired == 0)
        #expect(extractor.callCount == 0)
    }

    @Test func nonEpubFormatIsSkipped() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        let fileName = "scan.pdf"
        try writeReadableFile(fileName, in: root)
        let book = Book(title: "scan", author: "", fileName: fileName, format: .pdf)
        context.insert(book)
        try context.save()

        let extractor = FakeExtractor(.success(ExtractedBookMetadata(title: "X", author: "Y", coverImageData: Data([1]))))
        let service = makeService(extractor: extractor, root: root)

        let repaired = await service.repairIfNeeded(context: context)

        #expect(repaired == 0)
        #expect(extractor.callCount == 0)
    }

    @Test func extractorFailureLeavesRowAndManifestIntactForRetry() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        let fileName = "AAAAAAAA-1111-2222-3333-444444444444.epub"
        try writeReadableFile(fileName, in: root)
        let bookId = UUID()
        let book = Book(title: "AAAAAAAA-1111-2222-3333-444444444444", author: "", fileName: fileName, format: .epub)
        book.id = bookId
        context.insert(book)
        try context.save()

        // 既有（髒）manifest 不可被刪
        let store = BookManifestStore(rootDirectory: root)
        try store.write(BookManifest(
            bookId: bookId,
            fileName: fileName,
            originalFileName: nil,
            title: "AAAAAAAA-1111-2222-3333-444444444444",
            author: "",
            format: .epub,
            coverImageData: nil,
            dateAdded: Date(timeIntervalSince1970: 1),
            dateLastRead: nil,
            progression: 0.3,
            lastReadLocatorJSON: nil,
            preferredNotebookId: nil
        ))

        let extractor = FakeExtractor(.failure(ExtractFailure()))
        let service = makeService(extractor: extractor, root: root)

        let repaired = await service.repairIfNeeded(context: context)

        #expect(repaired == 0)
        #expect(extractor.callCount == 1)
        // row 不變
        let saved = try #require(try context.fetch(FetchDescriptor<Book>()).first)
        #expect(saved.title == "AAAAAAAA-1111-2222-3333-444444444444")
        // manifest 仍在、未被刪、progress 保留
        let manifest = try store.read(bookId: bookId)
        #expect(manifest.progression == 0.3)

        // 下次重試仍會呼叫 extractor（候選資格不變）
        #expect(service.needsRepair(saved))
    }

    // MARK: - skip 標記（避免每次啟動重 parse 無 metadata 的 EPUB）

    @Test func unfixableBookIsSkipMarkedAndNotReparsedOnSecondRun() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        let fileName = "BBBBBBBB-1111-2222-3333-444444444444.epub"
        try writeReadableFile(fileName, in: root)
        let book = Book(title: "BBBBBBBB-1111-2222-3333-444444444444", author: "", fileName: fileName, format: .epub)
        context.insert(book)
        try context.save()

        // EPUB 內也沒有可用 metadata（Readium 佔位值）
        let extractor = FakeExtractor(.success(ExtractedBookMetadata(title: "Untitled", author: "Unknown", coverImageData: nil)))
        let service = makeService(extractor: extractor, root: root)

        // 第一次：嘗試、開檔、補不齊 → 不修改、標記跳過
        let first = await service.repairIfNeeded(context: context)
        #expect(first == 0)
        #expect(extractor.callCount == 1)
        let saved = try #require(try context.fetch(FetchDescriptor<Book>()).first)
        #expect(saved.title == "BBBBBBBB-1111-2222-3333-444444444444")
        #expect(!service.needsRepair(saved))  // 已被 skip 標記

        // 第二次：不再開檔（extractor 不被呼叫）
        let second = await service.repairIfNeeded(context: context)
        #expect(second == 0)
        #expect(extractor.callCount == 1)
    }

    @Test func extractorThrowIsNotSkipMarkedSoItRetries() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        let fileName = "CCCCCCCC-1111-2222-3333-444444444444.epub"
        try writeReadableFile(fileName, in: root)
        let book = Book(title: "CCCCCCCC-1111-2222-3333-444444444444", author: "", fileName: fileName, format: .epub)
        context.insert(book)
        try context.save()

        let extractor = FakeExtractor(.failure(ExtractFailure()))
        let service = makeService(extractor: extractor, root: root)

        _ = await service.repairIfNeeded(context: context)
        #expect(extractor.callCount == 1)

        // throw 不標記跳過 → 第二次仍重試（暫時性錯誤可恢復）
        _ = await service.repairIfNeeded(context: context)
        #expect(extractor.callCount == 2)
    }

    @Test func partialFixThenSkipMarksWhenTitleStaysFallback() async throws {
        let container = try makeContainer()
        let context = ModelContext(container)
        let root = try makeTempRoot()
        defer { try? FileManager.default.removeItem(at: root) }

        let fileName = "DDDDDDDD-1111-2222-3333-444444444444.epub"
        try writeReadableFile(fileName, in: root)
        let book = Book(title: "DDDDDDDD-1111-2222-3333-444444444444", author: "", fileName: fileName, format: .epub)
        context.insert(book)
        try context.save()

        // EPUB 補得到 cover，但 title/author 仍是佔位 → cover 補上、仍 fallback → 標記跳過
        let extractor = FakeExtractor(.success(ExtractedBookMetadata(title: "Untitled", author: "Unknown", coverImageData: Data([7, 8]))))
        let service = makeService(extractor: extractor, root: root)

        let first = await service.repairIfNeeded(context: context)
        #expect(first == 1)  // cover 改了
        #expect(extractor.callCount == 1)
        let saved = try #require(try context.fetch(FetchDescriptor<Book>()).first)
        #expect(saved.coverImageData == Data([7, 8]))
        #expect(saved.title == "DDDDDDDD-1111-2222-3333-444444444444")  // title 沒被佔位值覆蓋
        #expect(!service.needsRepair(saved))  // 已 skip：不會為了補不到的 title 每次重 parse

        let second = await service.repairIfNeeded(context: context)
        #expect(second == 0)
        #expect(extractor.callCount == 1)
    }
}
#endif
