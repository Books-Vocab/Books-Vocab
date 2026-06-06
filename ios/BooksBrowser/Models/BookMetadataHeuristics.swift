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
}
