//
//  VocabularyEntry.swift
//  Books & Vocab
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

enum VocabularyCardRole: String, Codable, CaseIterable {
    case learning
    case dictionary
}

enum VocabularyPromotionState: String, Codable, CaseIterable {
    case idle
    case queued
    case running
    case failed
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
    /// Durable optimistic outbox bit. While true, sync must not overwrite the
    /// local reader visibility intent with an older server projection.
    var readerVisibilitySyncPending: Bool = false

    // Dictionary-card lifecycle. Stored raw strings preserve lightweight
    // migration for existing SwiftData rows and keep unknown future values
    // fail-soft through the typed accessors below.
    var cardRoleRaw: String = VocabularyCardRole.learning.rawValue
    var reviewEligible: Bool = true
    var promotionStateRaw: String = VocabularyPromotionState.idle.rawValue
    var promotedAt: Date?

    // Provider-neutral dictionary snapshot/provenance. The normalized payload
    // remains JSON so provider schema growth doesn't require a SwiftData model
    // migration for every optional lexical field.
    var dictionaryPayloadJSON: String?
    var dictionaryProvider: String?
    var dictionaryId: String?
    var dictionaryEntryKey: String?
    var dictionarySelectedSenseKey: String?
    var dictionarySelectedExampleKey: String?
    var dictionarySourceURL: String?
    var dictionaryLicenseName: String?
    var dictionaryLicenseURL: String?
    var dictionaryAttributionText: String?
    var dictionaryFetchedAt: Date?

    // Local spaced-review state
    var reviewIntervalHours: Double = VocabularyReviewPolicy.initialIntervalHours
    var nextReviewAt: Date = Date().addingTimeInterval(VocabularyReviewPolicy.initialIntervalHours * 3600)
    var lastReviewedAt: Date?
    var reviewCount: Int = 0
    var lapseCount: Int = 0
    var reviewStreak: Int = 0
    var lastReviewFeedbackRaw: Int = -1

    /// When this card's SRS state was last accepted by the backend.
    ///
    /// Without it the client had no way to tell "the server already has this
    /// schedule" from "this changed", so every sync re-sent every synced card's
    /// review state (644 cards in production) for the server to compare and
    /// mostly discard. Optional so existing rows arrive as `nil` and are sent
    /// once — the backend schedules from `next_review_at`, so a card it has
    /// never heard about must still be reported at least once.
    var reviewStateSyncedAt: Date?

    /// Whether the backend is missing this card's current SRS state.
    ///
    /// Compares against `lastReviewedAt ?? dateAdded`, the same instant the push
    /// payload sends as `last_reviewed_at`, so "what we told the server" and
    /// "what we compare against" cannot drift apart.
    var needsReviewStatePush: Bool {
        guard let syncedAt = reviewStateSyncedAt else { return true }
        return (lastReviewedAt ?? dateAdded) > syncedAt
    }

    var notebookId: String = "default"
    var bookId: UUID?
    var isDemoEntry: Bool = false

    // i18n: source/target language captured when this entry was created.
    // Optional for SwiftData lightweight migration — existing rows keep nil
    // until they're touched. Upload to server is gated by
    // `KGFeatureFlags.vocabularyLangPayloadEnabled` (backend currently has
    // `extra='ignore'` so the fields would be silently dropped today).
    var sourceLang: String?
    var targetLang: String?

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
    var shouldAppearInReview: Bool { shouldAppearInKnowledgeList && reviewEligible }
    var shouldAppearInKnowledgeList: Bool { isSynced && syncAction != .delete && !isArchived }
    var shouldAppearInArchiveList: Bool { isSynced && syncAction != .delete && isArchived }
    var effectiveDateAdded: Date { promotedAt ?? dateAdded }

    var cardRole: VocabularyCardRole {
        get { VocabularyCardRole(rawValue: cardRoleRaw) ?? .learning }
        set { cardRoleRaw = newValue.rawValue }
    }

    var promotionState: VocabularyPromotionState {
        get { VocabularyPromotionState(rawValue: promotionStateRaw) ?? .idle }
        set { promotionStateRaw = newValue.rawValue }
    }

    /// Shared `#Predicate` for SwiftData `@Query` knowledge-list call sites.
    /// `#Predicate` can't reference the `shouldAppearInKnowledgeList` computed
    /// property (it needs stored keypaths), so the condition is expressed once
    /// here — keeping KGVocabView / NotebookListView from drifting. Pass
    /// `notebookId` to additionally scope to one notebook.
    static func knowledgeListPredicate(notebookId: String? = nil) -> Predicate<VocabularyEntry> {
        if let notebookId {
            return #Predicate {
                $0.syncStatus == 1 && $0.actionType != "delete" && $0.isArchived == false && $0.notebookId == notebookId
            }
        }
        return #Predicate {
            $0.syncStatus == 1 && $0.actionType != "delete" && $0.isArchived == false
        }
    }

    init(
        word: String,
        translation: String,
        context: String,
        explanation: String? = nil,
        partOfSpeech: String? = nil,
        bookTitle: String,
        chapterTitle: String? = nil,
        sourceLang: String? = nil,
        targetLang: String? = nil
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
        // Default to the user's current translation language pair if caller
        // didn't override. Captured at creation time so future schema changes
        // can analyse per-locale usage without backfilling.
        self.sourceLang = sourceLang ?? TranslationLanguage.currentSource.rawValue
        self.targetLang = targetLang ?? TranslationLanguage.currentTarget.rawValue
    }
}

extension VocabularyEntry {
    /// 解析 notebookId 候選值，若不存在或已 soft-deleted → 回 "default"。
    ///
    /// 純函數。所有把使用者輸入 / 上層 binding 的 notebook id 寫入 `VocabularyEntry`
    /// 之前都應該走這裡，避免 race condition 把孤兒 entry 塞進已刪 notebook。
    /// 與 `SyncCoordinator.sanitizeOutbox` 形成 defense-in-depth。
    ///
    /// 「default」是 server-side sentinel，即使 local 出現 `Notebook(remoteId="default", isSoftDeleted=true)`
    /// 的損壞紀錄也必須回 "default" — 這是刻意的 short-circuit，don't "fix" it。
    ///
    /// **Cold-start guard**：若 local Notebook 表完全空（首次登入 / 尚未 reconcile），
    /// 直接回原候選值 — 此時無從判斷候選是否合法，誤判 fallback 到 default 會
    /// 永久污染 outbox。對齊 `ReaderView.sanitizeStaleBoundNotebook` 的「liveNotebooks
    /// 為空時 bail」契約。
    static func resolveNotebookId(
        _ candidate: String,
        in context: ModelContext
    ) -> String {
        if candidate.isEmpty || candidate == "default" { return "default" }

        // Cold-start guard: 表完全空 → 不夠資訊判斷，回原值
        let totalCount = (try? context.fetchCount(FetchDescriptor<Notebook>())) ?? 0
        guard totalCount > 0 else { return candidate }

        let descriptor = FetchDescriptor<Notebook>(
            predicate: #Predicate { $0.remoteId == candidate && !$0.isSoftDeleted }
        )
        let count = (try? context.fetchCount(descriptor)) ?? 0
        return count > 0 ? candidate : "default"
    }

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

    func queueReaderVisibility(_ hidden: Bool) {
        isExcludedFromReader = hidden
        readerVisibilitySyncPending = true
    }

    /// Restores the complete durable outbox state when the local SwiftData
    /// save for an optimistic visibility toggle fails.
    func restoreReaderVisibilityAfterSaveFailure(
        previousHidden: Bool,
        previousPending: Bool
    ) {
        isExcludedFromReader = previousHidden
        readerVisibilitySyncPending = previousPending
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
    func mutateLink(id linkId: String, _ transform: (KGCardLinkSummary) -> KGCardLinkSummary?) -> (kind: String, link: KGCardLinkSummary)? {
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
            return (kind: kind, link: original)
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
