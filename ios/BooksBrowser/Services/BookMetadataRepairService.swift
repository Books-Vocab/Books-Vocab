#if os(iOS)
import Foundation
import SwiftData

/// 從本機可讀 EPUB 重抽 metadata，修復被 UUID fallback 污染的 Book row 與 manifest。
///
/// 背景：曾有書的 row 與 `.metadata` manifest 都被 fallback 值污染（title=UUID、
/// cover=0），但 EPUB 檔本身在本機可讀。manifest 回填救不了（manifest 也是髒的），
/// 只能從 EPUB 重新抽。本 service 在 UI 掛載後啟動一次，逐本修復。
///
/// 原則（對齊修復計畫）：
/// - 只處理 `.epub` 且本機可讀的檔；**不**觸發 iCloud 下載、不等 placeholder、不阻塞啟動。
/// - 只做「高信心改善」：fallback title→真 title、空 author→真 author、nil cover→真 cover。
///   不用 EPUB 的 `Untitled` / UUID / 檔名 base 覆蓋，不覆蓋已乾淨的欄位。
/// - 抽取失敗（throw）只 log，**不**刪 row、不刪 manifest、**不**標記跳過，下次啟動可重試
///   （可能是 iCloud / lock 暫時性）。
/// - 抽取**成功但 EPUB 仍榨不出可用 metadata** → 記 per-file 跳過標記，避免每次冷啟動都重
///   `openPublication`（實測大書達 13–28 秒）。標記以 `logicVersion` 版號隔離：未來改進抽取
///   邏輯時 bump 版號即讓整批舊標記失效、重新嘗試。
/// - 修好的 row 經 `BookManifestStore.write(book:)`（merge-on-write）重寫 manifest，
///   只替換 title/author/cover，保留 bookId/fileName/dateAdded/progression/locator/notebook。
@MainActor
final class BookMetadataRepairService {
    /// 抽取邏輯版本。bump 會讓所有舊跳過標記失效（key 帶版號），對「曾判定無可用 metadata」
    /// 的書重新嘗試。改 extractor / heuristics 行為時記得 +1。
    private static let logicVersion = 1

    private let extractor: any BookMetadataExtracting
    private let manifestStore: BookManifestStore
    private let fileManager: FileManager
    private let userDefaults: UserDefaults
    private let fileURLProvider: (Book) -> URL
    private var isRunning = false

    private var skipDefaultsKey: String { "kg_metadata_repair_skip_v\(Self.logicVersion)" }

    init(
        extractor: any BookMetadataExtracting,
        manifestStore: BookManifestStore = BookManifestStore(),
        fileManager: FileManager = .default,
        userDefaults: UserDefaults = .standard,
        fileURLProvider: @escaping (Book) -> URL = { $0.fileURL }
    ) {
        self.extractor = extractor
        self.manifestStore = manifestStore
        self.fileManager = fileManager
        self.userDefaults = userDefaults
        self.fileURLProvider = fileURLProvider
    }

    /// 掃描需要修復的 EPUB row 並逐本修復。回傳實際被修好的本數。
    ///
    /// in-flight guard 防同一 launch 重入；非候選（已乾淨 / 不可讀 / 非 epub）完全不開
    /// EPUB，所以重複呼叫（如語言切換重建 view tree）對乾淨書庫近乎零成本。
    @discardableResult
    func repairIfNeeded(context: ModelContext) async -> Int {
        guard !isRunning else { return 0 }
        isRunning = true
        defer { isRunning = false }

        let books: [Book]
        do {
            books = try context.fetch(FetchDescriptor<Book>())
        } catch {
            AppLog.book.error("metadata repair: fetch failed: \(error.localizedDescription)")
            return 0
        }

        let candidates = books.filter { needsRepair($0) }
        guard !candidates.isEmpty else { return 0 }

        var repaired = 0
        for book in candidates where await repair(book) {
            repaired += 1
        }

        if repaired > 0 {
            do {
                try context.save()
            } catch {
                AppLog.book.error("metadata repair: save failed: \(error.localizedDescription)")
            }
        }
        AppLog.book.info("metadata repair: candidates=\(candidates.count) repaired=\(repaired)")
        return repaired
    }

    /// 是否為修復候選：epub + 本機可讀 + row 帶 fallback title/author。
    ///
    /// 候選門檻刻意只認 fallback title / author（污染的強訊號），不把「title 乾淨但
    /// cover=nil」單獨列入——否則本來就沒封面的書每次啟動都會重 parse EPUB，違反
    /// 「不在啟動路徑做重 IO」。cover 在候選的修復過程中順帶補。
    func needsRepair(_ book: Book) -> Bool {
        guard book.format == .epub else { return false }
        guard !isSkipped(book.epubFileName) else { return false }
        guard fileManager.isReadableFile(atPath: fileURLProvider(book).path) else { return false }
        return hasFallbackMetadata(book)
    }

    /// row 是否帶 fallback title / author（封面缺失不單獨算，理由見 needsRepair 註解）。
    private func hasFallbackMetadata(_ book: Book) -> Bool {
        BookMetadataHeuristics.looksLikeFallbackTitle(book.title, fileName: book.epubFileName)
            || BookMetadataHeuristics.looksLikeFallbackAuthor(book.author)
    }

    private func isSkipped(_ fileName: String) -> Bool {
        (userDefaults.array(forKey: skipDefaultsKey) as? [String])?.contains(fileName) ?? false
    }

    private func markSkipped(_ fileName: String) {
        var set = Set((userDefaults.array(forKey: skipDefaultsKey) as? [String]) ?? [])
        guard set.insert(fileName).inserted else { return }
        userDefaults.set(Array(set), forKey: skipDefaultsKey)
    }

    /// 修復單本。回傳是否有任何欄位被改寫。
    private func repair(_ book: Book) async -> Bool {
        let extracted: ExtractedBookMetadata
        do {
            extracted = try await extractor.extractMetadata(fromEPUBAt: fileURLProvider(book))
        } catch {
            // 不刪 row、不刪 manifest，下次啟動可重試。
            AppLog.book.warning("metadata repair: extract failed (\(book.epubFileName, privacy: .public)): \(error.localizedDescription)")
            return false
        }

        var changed = false
        // 每個欄位獨立重檢 fallback：候選資格（needsRepair）是 title OR author 的或邏輯，
        // 一本可能只因 author 不合格而入選、title 其實乾淨——此處重檢確保只覆蓋真正
        // fallback 的欄位。刻意不與 needsRepair 的 OR 合併，勿在 refactor 時摺疊。
        if BookMetadataHeuristics.looksLikeFallbackTitle(book.title, fileName: book.epubFileName),
           BookMetadataHeuristics.isUsableExtractedTitle(extracted.title, fileName: book.epubFileName) {
            book.title = extracted.title.trimmingCharacters(in: .whitespacesAndNewlines)
            changed = true
        }
        if BookMetadataHeuristics.looksLikeFallbackAuthor(book.author),
           BookMetadataHeuristics.isUsableExtractedAuthor(extracted.author) {
            book.author = extracted.author.trimmingCharacters(in: .whitespacesAndNewlines)
            changed = true
        }
        if book.coverImageData == nil, let cover = extracted.coverImageData, !cover.isEmpty {
            book.coverImageData = cover
            changed = true
        }

        if changed {
            // merge-on-write：保留 manifest 既有 progress/locator/notebook/dateAdded，
            // 只讓修好的 title/author/cover 取代髒值。
            manifestStore.writeBestEffort(book: book)
        }

        // 抽取成功但 row 仍帶 fallback title/author（EPUB 內就沒有可用 metadata）→ 標記跳過，
        // 別在之後每次冷啟動都重 parse 這顆（openPublication 實測 13–28s）。cover 補不補不影響：
        // 候選資格只看 title/author。檔案被換 = 新 fileName，stale 標記無害。
        if hasFallbackMetadata(book) {
            markSkipped(book.epubFileName)
            AppLog.book.info("metadata repair: skip-marked \(book.epubFileName, privacy: .public) (EPUB lacks usable metadata)")
        }
        return changed
    }
}
#endif
