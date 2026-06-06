import Foundation

/// 書籍 metadata 的 fallback 判定 — 在 reconciler、manifest 寫入、metadata repair
/// 之間共享，避免「UUID title / 空 author / nil cover」這類 fallback 值被當成真資料
/// 固化進 row 或 manifest。
enum BookMetadataHeuristics {
    /// title 是否為 fallback（= 檔名 base，或本身是 UUID 字串）。
    ///
    /// 語意刻意與既有 reconciler 行為一致，僅抽出共享，不改變判定結果。
    static func looksLikeFallbackTitle(_ title: String, fileName: String) -> Bool {
        let baseName = URL(fileURLWithPath: fileName).deletingPathExtension().lastPathComponent
        return title == baseName || UUID(uuidString: title) != nil
    }

    /// author 是否為 fallback（空字串或 `"Unknown"`）。
    static func looksLikeFallbackAuthor(_ author: String) -> Bool {
        author.isEmpty || author == "Unknown"
    }

    /// 從 EPUB 抽出的 title 是否「可用來覆蓋 fallback」。
    ///
    /// 拒絕：空白、Readium 的佔位 `"Untitled"`、UUID、與檔名 base 相同——這些都不是
    /// 真書名，覆蓋上去只是換一種髒。
    static func isUsableExtractedTitle(_ title: String, fileName: String) -> Bool {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed != "Untitled" else { return false }
        return !looksLikeFallbackTitle(trimmed, fileName: fileName)
    }

    /// 從 EPUB 抽出的 author 是否可用（非空、非 Readium 佔位 `"Unknown"`）。
    static func isUsableExtractedAuthor(_ author: String) -> Bool {
        let trimmed = author.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty && trimmed != "Unknown"
    }
}
