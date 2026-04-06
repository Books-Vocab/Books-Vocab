//
//  VocabularyEntry.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import Foundation
import SwiftData

enum VocabularySyncState: Int, Codable {
    case pending = 0
    case synced = 1
    case failed = 2
}

enum VocabularySyncAction: String, Codable {
    case add
    case delete
    case edit
}

/// 生詞條目 — 記錄使用者在閱讀中查詢的單字/短語
@Model
final class VocabularyEntry {
    // Note: #Index requires iOS 18+. On iOS 17, queries work without
    // indexes but may be slower for large datasets. Consider adding
    // #Index back behind #available when iOS 17 support is dropped.

    var id: UUID
    var word: String                // 原文單字或短語
    var translation: String         // 翻譯結果
    var context: String             // 來源句子（上下文）
    var explanation: String?        // AI 語境解釋
    var partOfSpeech: String?       // 詞性
    var bookTitle: String           // 來源書名
    var chapterTitle: String?       // 來源章節
    var dateAdded: Date

    // Inflection forms for underlining (e.g. "lay" → ["lay","lays","laid","laying","lain"])
    var rootForm: String?           // AI-determined lemma, sent to server on sync
    var inflections: [String] = []  // filled by server after sync

    // KG Integration
    var syncStatus: Int = 0         // 0=pending, 1=synced, 2=failed
    var kgCardId: String?           // KG 卡片 ID（同步後回填）
    var difficultyTier: String?     // "core" / "intermediate" / "advanced" / "rare"
    var actionType: String = "add"  // "add" | "delete" | "edit"
    var reviewModeRaw: String = VocabularyCardMode.recognition.rawValue
    var reviewExamples: [String] = []
    var collocations: [String] = []
    var collocationExplanationsJSON: String = "{}"
    var graphLinksJSON: String = "{}"
    var isArchived: Bool = false
    var isExcludedFromReader: Bool = false

    // Local spaced-review state
    var reviewIntervalHours: Double = VocabularyReviewPolicy.initialIntervalHours
    var nextReviewAt: Date = Date().addingTimeInterval(VocabularyReviewPolicy.initialIntervalHours * 3600)
    var lastReviewedAt: Date?
    var reviewCount: Int = 0
    var lapseCount: Int = 0
    var reviewStreak: Int = 0
    var lastReviewFeedbackRaw: Int = -1

    var notebookId: String = "default"
    var bookId: UUID?
    var isDemoEntry: Bool = false

    @Transient private var _graphLinksCache: [String: [KGCardLinkSummary]]?
    @Transient private var _graphLinksCacheKey: String?

    /// Sync status convenience
    var syncState: VocabularySyncState {
        get { VocabularySyncState(rawValue: syncStatus) ?? .pending }
        set { syncStatus = newValue.rawValue }
    }

    var syncAction: VocabularySyncAction {
        get { VocabularySyncAction(rawValue: actionType) ?? .add }
        set { actionType = newValue.rawValue }
    }

    var isFailed: Bool { syncState == .failed }
    var isSynced: Bool { syncState == .synced }
    var isPending: Bool { syncState == .pending }
    var isPendingAdd: Bool { syncState == .pending && syncAction == .add }
    var isPendingDelete: Bool { syncState == .pending && syncAction == .delete }
    var isFailedAdd: Bool { syncState == .failed && syncAction == .add }
    var isFailedDelete: Bool { syncState == .failed && syncAction == .delete }
    var shouldUploadOnNextSync: Bool { isPendingAdd || isPendingDelete || isFailedAdd || isFailedDelete }
    var shouldAppearInReader: Bool { syncAction != .delete && !isArchived && !isExcludedFromReader }
    var shouldAppearInKnowledgeList: Bool { isSynced && syncAction != .delete && !isArchived }
    var shouldAppearInArchiveList: Bool { isSynced && syncAction != .delete && isArchived }

    init(
        word: String,
        translation: String,
        context: String,
        explanation: String? = nil,
        partOfSpeech: String? = nil,
        bookTitle: String,
        chapterTitle: String? = nil
    ) {
        self.id = UUID()
        self.word = word
        self.translation = translation
        self.context = context
        self.explanation = explanation
        self.partOfSpeech = partOfSpeech
        self.bookTitle = bookTitle
        self.chapterTitle = chapterTitle
        self.dateAdded = Date()
    }
}

extension VocabularyEntry {
    func queueDelete() {
        syncAction = .delete
        syncState = .pending
    }

    func restorePendingEntry() {
        syncAction = .add
        syncState = .pending
    }

    func markSynced() {
        syncAction = .add
        syncState = .synced
    }

    func markSyncFailed() {
        syncState = .failed
    }

    func prepareForRetryAttempt() {
        if isFailed {
            syncState = .pending
        }
    }

    var reviewMode: VocabularyCardMode {
        get { VocabularyCardMode(rawValue: reviewModeRaw) ?? .recognition }
        set { reviewModeRaw = newValue.rawValue }
    }

    var primaryReviewExample: String? {
        reviewExamples.first { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } ??
        (context.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : markWordInContext(context))
    }

    var allReviewExamples: [String] {
        let remoteExamples = reviewExamples.filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        if remoteExamples.isEmpty {
            let trimmed = context.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? [] : [markWordInContext(trimmed)]
        }
        return remoteExamples
    }

    private static let regexCache = NSCache<NSString, NSRegularExpression>()

    private static func cachedRegex(pattern: String, options: NSRegularExpression.Options = .caseInsensitive) -> NSRegularExpression? {
        let key = pattern as NSString
        if let cached = regexCache.object(forKey: key) { return cached }
        guard let regex = try? NSRegularExpression(pattern: pattern, options: options) else { return nil }
        regexCache.setObject(regex, forKey: key)
        return regex
    }

    /// 在 context 純文字中為 word 加上 **markdown** 標記（模擬 server 的 _build_example 邏輯）
    private func markWordInContext(_ text: String) -> String {
        let escaped = NSRegularExpression.escapedPattern(for: word)
        if let regex = Self.cachedRegex(pattern: escaped),
           let match = regex.firstMatch(in: text, range: NSRange(location: 0, length: (text as NSString).length)) {
            let ns = text as NSString
            let matched = ns.substring(with: match.range)
            return ns.replacingCharacters(in: match.range, with: "**\(matched)**")
        }
        // stem fallback: 前 4-6 字元
        let firstWord = word.components(separatedBy: " ").first ?? word
        if firstWord.count >= 4 {
            let stem = String(firstWord.prefix(min(firstWord.count, 6)))
            let stemEsc = NSRegularExpression.escapedPattern(for: stem)
            let stemPat = "(?<![\\w\\p{L}])\(stemEsc)\\w*(?![\\w\\p{L}])"
            if let stemRegex = Self.cachedRegex(pattern: stemPat),
               let match = stemRegex.firstMatch(in: text, range: NSRange(location: 0, length: (text as NSString).length)) {
                let ns = text as NSString
                let matched = ns.substring(with: match.range)
                return ns.replacingCharacters(in: match.range, with: "**\(matched)**")
            }
        }
        return text
    }

    // MARK: - Link mutation helpers

    /// Finds a link by `id` across all kind-groups, applies `transform`, and returns the original.
    /// - If `transform` returns a new link → replaces in-place.
    /// - If `transform` returns `nil` → removes (and cleans up empty groups).
    /// - Returns `nil` when no link with the given `id` exists.
    @discardableResult
    func mutateLink(id linkId: String, _ transform: (KGCardLinkSummary) -> KGCardLinkSummary?) -> (kind: String, original: KGCardLinkSummary)? {
        var dict = graphLinksByKind
        for (kind, links) in dict {
            guard let idx = links.firstIndex(where: { $0.id == linkId }) else { continue }
            let original = links[idx]
            if let replacement = transform(original) {
                dict[kind]?[idx] = replacement
            } else {
                dict[kind]?.remove(at: idx)
                if dict[kind]?.isEmpty == true { dict[kind] = nil }
            }
            graphLinksByKind = dict
            return (kind: kind, original: original)
        }
        return nil
    }

    /// Re-inserts a link into a specific kind-group (used for rollback after delete).
    func insertLink(_ link: KGCardLinkSummary, kind: String) {
        var dict = graphLinksByKind
        dict[kind, default: []].append(link)
        graphLinksByKind = dict
    }

    var collocationExplanations: [String: String] {
        get {
            guard let data = collocationExplanationsJSON.data(using: .utf8),
                  let dict = try? JSONDecoder().decode([String: String].self, from: data)
            else { return [:] }
            return dict
        }
        set {
            collocationExplanationsJSON = (try? JSONEncoder().encode(newValue))
                .flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
        }
    }

    var graphLinksByKind: [String: [KGCardLinkSummary]] {
        get {
            // Invalidate cache when underlying JSON changes (e.g. cross-context sync)
            if let cached = _graphLinksCache, _graphLinksCacheKey == graphLinksJSON {
                return cached
            }
            guard let data = graphLinksJSON.data(using: .utf8) else { return [:] }
            let decoded = (try? JSONDecoder().decode([String: [KGCardLinkSummary]].self, from: data)) ?? [:]
            _graphLinksCache = decoded
            _graphLinksCacheKey = graphLinksJSON
            return decoded
        }
        set {
            _graphLinksCache = newValue
            guard
                let data = try? JSONEncoder().encode(newValue),
                let json = String(data: data, encoding: .utf8)
            else {
                graphLinksJSON = "{}"
                _graphLinksCacheKey = "{}"
                return
            }
            graphLinksJSON = json
            _graphLinksCacheKey = json
        }
    }
}
