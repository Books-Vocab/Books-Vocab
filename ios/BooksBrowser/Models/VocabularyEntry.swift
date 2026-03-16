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
    #Index<VocabularyEntry>(
        [\.syncStatus, \.actionType],
        [\.word],
        [\.isArchived],
        [\.nextReviewAt]
    )

    var id: UUID
    var word: String                // 原文單字或短語
    var translation: String         // 翻譯結果
    var context: String             // 來源句子（上下文）
    var explanation: String?        // AI 語境解釋
    var partOfSpeech: String?       // 詞性
    var pronunciation: String?      // 音標
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
    var graphLinksJSON: String = "{}"
    var isArchived: Bool = false

    // Local spaced-review state
    var reviewIntervalHours: Double = VocabularyReviewPolicy.initialIntervalHours
    var nextReviewAt: Date = Date().addingTimeInterval(VocabularyReviewPolicy.initialIntervalHours * 3600)
    var lastReviewedAt: Date?
    var reviewCount: Int = 0
    var lapseCount: Int = 0
    var reviewStreak: Int = 0
    var lastReviewFeedbackRaw: Int = -1

    var bookId: UUID?
    var isDemoEntry: Bool = false

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
    var shouldAppearInReader: Bool { syncAction != .delete && !isArchived }
    var shouldAppearInKnowledgeList: Bool { isSynced && syncAction != .delete && !isArchived }
    var shouldAppearInArchiveList: Bool { isSynced && syncAction != .delete && isArchived }

    init(
        word: String,
        translation: String,
        context: String,
        explanation: String? = nil,
        partOfSpeech: String? = nil,
        pronunciation: String? = nil,
        bookTitle: String,
        chapterTitle: String? = nil
    ) {
        self.id = UUID()
        self.word = word
        self.translation = translation
        self.context = context
        self.explanation = explanation
        self.partOfSpeech = partOfSpeech
        self.pronunciation = pronunciation
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
        (context.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : context)
    }

    var allReviewExamples: [String] {
        let remoteExamples = reviewExamples.filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        if remoteExamples.isEmpty {
            return context.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? [] : [context]
        }
        return remoteExamples
    }

    var graphLinksByKind: [String: [KGCardLinkSummary]] {
        get {
            guard let data = graphLinksJSON.data(using: .utf8) else { return [:] }
            return (try? JSONDecoder().decode([String: [KGCardLinkSummary]].self, from: data)) ?? [:]
        }
        set {
            guard
                let data = try? JSONEncoder().encode(newValue),
                let json = String(data: data, encoding: .utf8)
            else {
                graphLinksJSON = "{}"
                return
            }
            graphLinksJSON = json
        }
    }
}
